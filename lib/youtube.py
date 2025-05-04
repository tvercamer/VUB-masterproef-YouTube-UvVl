# Import libraries
import os
import pickle
import datetime
import pandas as pd
from lib.helpers import parse_duration
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Determine which YouTube API's to use
SCOPES = [
    'https://www.googleapis.com/auth/youtube.readonly',  # YouTube Data API
    'https://www.googleapis.com/auth/yt-analytics.readonly',  # YouTube Analytics API
    'https://www.googleapis.com/auth/youtube.force-ssl'  # Allows fetching comments
]

# Define paths for credentials
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_PATH = os.path.join(ROOT_DIR, 'token.pickle')
CLIENT_SECRET_PATH = os.path.join(ROOT_DIR, 'client_secret.json')


# YouTube Authentication
def authenticate_youtube():
    """Handles OAuth 2.0 authentication and returns an authorized API client."""
    credentials = None

    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'rb') as token:
            credentials = pickle.load(token)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
            credentials = flow.run_local_server(port=0)

        with open(TOKEN_PATH, 'wb') as token:
            pickle.dump(credentials, token)

    # Initialize API clients
    ytd = build('youtube', 'v3', credentials=credentials)
    yta = build('youtubeAnalytics', 'v2', credentials=credentials)
    return ytd, yta


# Get YouTube clients
ytd, yta = authenticate_youtube()


# API requests
def get_generic_info(video_ids):
    """
    Fetches generic video information from the YouTube Data API in batches.

    :param video_ids: List or NumPy array of video IDs.
    :return: DataFrame that contains generic information for each video.
    """
    video_data = []
    batch_size = 50  # API limit

    # Ensure video_ids is a list of strings
    video_ids = [str(vid) for vid in video_ids]

    # Split video IDs into batches of 50
    batches = [video_ids[i:i + batch_size] for i in range(0, len(video_ids), batch_size)]

    for batch in batches:
        try:
            request = ytd.videos().list(
                part='snippet,contentDetails,statistics',
                id=','.join(batch)  # Convert list to comma-separated string
            )
            response = request.execute()

            # Process API response
            if 'items' in response and response['items']:
                for item in response['items']:
                    statistics = item['statistics']
                    snippet = item['snippet']

                    # Get video ID and publish date
                    video_id = item['id']
                    publish_date = snippet['publishedAt']
                    shares = get_shares(video_id, publish_date)

                    # Calculate engagement rate
                    engagement = calc_engagement_rate(
                        shares,
                        int(statistics.get('commentCount', 0)),
                        int(statistics.get('likeCount', 0)),
                        int(statistics.get('dislikeCount', 0)),
                        int(statistics.get('viewCount', 1))  # Avoid division by zero
                    )

                    # Append to results
                    video_data.append({
                        'id': video_id,
                        'title': snippet['title'],
                        'publish_date': publish_date,
                        'duration': parse_duration(item['contentDetails']['duration']),
                        'views': int(statistics.get('viewCount', 0)),
                        'likes': int(statistics.get('likeCount', 0)),
                        'dislikes': int(statistics.get('dislikeCount', 0)),
                        'shares': shares,
                        'comments': int(statistics.get('commentCount', 0)),
                        'engagement': engagement
                    })

        except Exception as e:
            print(f'❌ Error fetching video data for batch: {batch}: {e}')

    # Convert list to DataFrame
    return pd.DataFrame(video_data).set_index('id')


def calc_engagement_rate(shares, comments, likes, dislikes, views):
    """
    Calculates the engagement rate for a video.

    :param shares: Integer with the number of shares.
    :param comments: Integer with the number of comments.
    :param likes: Integer with the number of likes.
    :param dislikes: Integer with the number of dislikes.
    :param views: Integer with the number of views.
    :return: Float with the engagement rate.
    """
    engagement_rate = (shares + comments + likes - dislikes) / views if views > 0 else 0
    return round(engagement_rate*100, 2)


def get_shares(video_id, start_date):
    """
    Fetches the number of shares for a specific video using the YouTube Analytics API.

    :param video_id: String with the video_id.
    :param start_date: String with the publishing date of the video.
    :return: Integer with the number of shares.
    """
    end_date = datetime.datetime.now().strftime('%Y-%m-%d')
    start_date = start_date.split('T')[0]
    try:
        response = yta.reports().query(
            ids='channel==MINE',
            startDate=start_date,
            endDate=end_date,
            metrics='shares',
            dimensions='video',
            filters=f'video=={video_id}'
        ).execute()

        if 'rows' in response and response['rows']:
            return int(response['rows'][0][1])
        else:
            print(f'⚠️ No data found for the provided video ID.')
            return None

    except Exception as e:
        print(f'❌ Error fetching video shares: {e}')
        return None


def get_metrics_over_time(videos):
    """
    Fetches private video data from YouTube Analytics API and restructures it
    so that each video has a single row with ordered columns for each metric type.
    If an interval hasn't passed yet, the value is set to None.

    :param videos: DataFrame with publicly available video info (index = 'id').
    :return: DataFrame with one row per video and multiple time interval columns.
    """

    # Define intervals (days after publish_date)
    time_intervals = {
        '24h': 1,
        '1w': 7,
        '2w': 14,
        '1m': 30,
        '2m': 60,
        '3m': 90
    }

    analytics_data = []
    today = datetime.date.today()  # Get today's date to check time intervals

    # Loop through videos
    for index, row in videos.iterrows():
        video_id = index
        publish_date = pd.to_datetime(row['publish_date']).date()
        video_data = {
            'id': video_id,
            'publish_date': row['publish_date']
        }

        # Temporary storage for sorting
        temp_views = {}
        temp_likes = {}
        temp_dislikes = {}
        temp_shares = {}
        temp_comments = {}
        temp_engagement = {}

        # Loop through time intervals and fetch data
        for interval, days_after in time_intervals.items():
            analytics_date = publish_date + datetime.timedelta(days=days_after)

            # If the interval hasn't passed yet, set None
            if analytics_date > today:
                temp_views[f'views_{interval}'] = None
                temp_likes[f'likes_{interval}'] = None
                temp_dislikes[f'dislikes_{interval}'] = None
                temp_shares[f'shares_{interval}'] = None
                temp_comments[f'comments_{interval}'] = None
                temp_engagement[f'engagement_rate_{interval}'] = None
                continue  # Skip fetching data

            try:
                request = yta.reports().query(
                    ids=f"channel=={os.getenv('YT_CHANNEL_ID')}",
                    startDate=str(publish_date),
                    endDate=str(analytics_date),
                    metrics='views,likes,dislikes,shares,comments',
                    filters=f'video=={video_id}'
                )
                response = request.execute()

                if 'rows' in response and response['rows']:
                    row_data = response['rows'][0]

                    # Store values in temporary dictionaries for correct ordering
                    temp_views[f'views_{interval}'] = row_data[0]
                    temp_likes[f'likes_{interval}'] = row_data[1]
                    temp_dislikes[f'dislikes_{interval}'] = row_data[2]
                    temp_shares[f'shares_{interval}'] = row_data[3]
                    temp_comments[f'comments_{interval}'] = row_data[4]
                    temp_engagement[f'engagement_rate_{interval}'] = calc_engagement_rate(
                        int(row_data[3]), int(row_data[4]), int(row_data[1]), int(row_data[2]), int(row_data[0])
                    )

                else:
                    # Fill missing data with None
                    temp_views[f'views_{interval}'] = None
                    temp_likes[f'likes_{interval}'] = None
                    temp_dislikes[f'dislikes_{interval}'] = None
                    temp_shares[f'shares_{interval}'] = None
                    temp_comments[f'comments_{interval}'] = None
                    temp_engagement[f'engagement_rate_{interval}'] = None

            except Exception as e:
                print(f'❌ Error fetching video data for video {video_id} on {analytics_date}: {e}')

        # Ensure correct column ordering
        video_data.update(temp_views)
        video_data.update(temp_likes)
        video_data.update(temp_dislikes)
        video_data.update(temp_shares)
        video_data.update(temp_comments)
        video_data.update(temp_engagement)

        # Append the structured data for this video
        analytics_data.append(video_data)

    # Convert to DataFrame
    df_analytics = pd.DataFrame(analytics_data)
    return df_analytics


def get_video_comments(videos):
    """
    Uses the YouTube Data API to get the comments (including replies) for each video.

    :param videos: DataFrame with publicly available video info.
    :return: DataFrame containing comments for each video.
    """
    all_comments = []

    # Ensure videos is a DataFrame and extract video IDs correctly
    video_ids = videos.index.tolist() if videos.index.name == "id" else videos.iloc[:, 0].tolist()

    for video_id in video_ids:
        video_id = str(video_id)  # Ensure it's a string
        next_page_token = None

        while True:
            try:
                request = ytd.commentThreads().list(
                    part='snippet,replies',
                    videoId=video_id,
                    maxResults=100,
                    textFormat='plainText',
                    pageToken=next_page_token
                )
                response = request.execute()

                # Extract top-level comments
                if 'items' in response:
                    for item in response['items']:
                        comment = item['snippet']['topLevelComment']['snippet']
                        comment_id = item['id']

                        all_comments.append({
                            'id': video_id,
                            'comment_id': comment_id,
                            'parent_comment_id': None,
                            'author': comment['authorDisplayName'],
                            'published_at': comment['publishedAt'],
                            'like_count': comment['likeCount'],
                            'comment_nl': comment['textDisplay'],
                            'is_reply': False
                        })

                        # Check for replies and retrieve them
                        if 'replies' in item:
                            for reply in item['replies']['comments']:
                                reply_snippet = reply['snippet']
                                all_comments.append({
                                    'id': video_id,
                                    'comment_id': reply['id'],
                                    'parent_comment_id': comment_id,
                                    'author': reply_snippet['authorDisplayName'],
                                    'published_at': reply_snippet['publishedAt'],
                                    'like_count': reply_snippet['likeCount'],
                                    'comment_nl': reply_snippet['textDisplay'],
                                    'is_reply': True
                                })

                # Check if there are more comments
                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    break

            except Exception as e:
                print(f'❌ Error fetching comments for video {video_id}: {e}')
                break

    # Convert to DataFrame
    df_comments = pd.DataFrame(all_comments)
    return df_comments if not df_comments.empty else None


def get_all_video_ids():
    """
    Fetches all unique video IDs from the uploads playlist of the YouTube channel defined in .env.
    """
    video_ids = set()
    next_page_token = None
    channel_id = os.getenv('YT_CHANNEL_ID')

    if not channel_id:
        raise ValueError("❌ YT_CHANNEL_ID is not set in the .env file.")

    # Step 1: Get the uploads playlist ID
    channel_response = ytd.channels().list(
        part='contentDetails',
        id=channel_id
    ).execute()
    uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

    # Step 2: Loop through the uploads playlist
    while True:
        playlist_response = ytd.playlistItems().list(
            part='contentDetails',
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=next_page_token
        ).execute()

        for item in playlist_response['items']:
            video_ids.add((
                item['contentDetails']['videoId'],
                item['contentDetails']['videoPublishedAt']
            ))

        next_page_token = playlist_response.get('nextPageToken')
        if not next_page_token:
            break

    # Convert back to list of dicts
    return [{'videoId': vid, 'publishedAt': date} for vid, date in video_ids]


def get_video_ids_in_period(start_date, end_date):
    """
    Returns video IDs published within the specified period.
    """
    all_videos = get_all_video_ids()
    start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.datetime.strptime(end_date, '%Y-%m-%d')

    filtered_videos = [
        vid['videoId'] for vid in all_videos
        if start_dt <= datetime.datetime.strptime(vid['publishedAt'], '%Y-%m-%dT%H:%M:%SZ') <= end_dt
    ]

    return filtered_videos
