# Import libraries
import re
import os
import isodate
import requests
from deep_translator import GoogleTranslator


def parse_duration(duration):
    """
    Converts YouTube's ISO 8601 duration (e.g., PT10M59S) into MM:SS format.

    :param duration: ISO 8601 duration string from YouTube API.
    :return: A formatted time string (e.g., '0:59').
    """
    try:
        duration_obj = isodate.parse_duration(duration)
        minutes, seconds = divmod(int(duration_obj.total_seconds()), 60)
        return f'{minutes}:{seconds:02d}'  # Ensures two-digit seconds format
    except Exception as e:
        print(f'❌ Error parsing duration: {e}')
        return 'N/A'


def translate_with_google(text):
    """
    Translates a given Dutch text to English using Google Translate.

    :param text: Dutch text string
    :return: Translated English text
    """
    try:
        translated_text = GoogleTranslator(source='nl', target='en').translate(text)
        return translated_text
    except Exception as e:
        print(f'❌ Translation error: {e}')
        return text  # If translation fails, return original text


def translate_with_deepl(text):
    """
    Translates a given Dutch text to English using the DeepL API.

    :param text: Dutch text string
    :return: Translated English text
    """
    url = "https://api.deepl.com/v2/translate"
    data = {
        "auth_key": os.getenv("DEEPL_API_KEY") ,
        "text": text,
        "source_lang": "NL",
        "target_lang": "EN"
    }

    try:
        response = requests.post(url, data=data)
        response.raise_for_status()  # Raises error if request failed
        result = response.json()
        translated_text = result['translations'][0]['text']
        return translated_text
    except Exception as e:
        print(f'❌ DeepL Translation error: {e}')
        return text  # Fallback: return original text


def anonymize_comments(comments):
    """
    Anonymizes authors in the comments except for '@UniversiteitvanVlaanderen'.
    Also replaces author mentions in the comment text.

    :param comments: DataFrame containing YouTube comments.
    :return: DataFrame with anonymized authors and updated comment_text.
    """
    # Dictionary to map original authors to "UserX" anonymized names
    author_mapping = {}
    user_count = 1

    def get_anonymized_author(author):
        nonlocal user_count
        if author == '@UniversiteitvanVlaanderen':
            return author  # Keep official account visible
        if author not in author_mapping:
            author_mapping[author] = f'User{user_count}'
            user_count += 1
        return author_mapping[author]

    # Anonymize author column
    comments['author'] = comments['author'].apply(get_anonymized_author)

    # Replace author names in the comment text
    def anonymize_text(comment):
        for original_author, anonymized in author_mapping.items():
            comment = re.sub(rf'@{re.escape(original_author)}', f'@{anonymized}', comment)
        return comment

    comments['comment_nl'] = comments['comment_nl'].apply(anonymize_text)

    return comments
