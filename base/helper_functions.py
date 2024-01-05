import re
import random
from .models import PhoneNumber,Picklist, MessageTracker, WeeklyTopic, Topic
import sys
import calendar
import vonage
from django.conf import settings
import pytz
from datetime import datetime, timezone, timedelta
import os
import requests
from ibm_watson import AssistantV2
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_watson import LanguageTranslatorV3
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core.api_exception import ApiException
import json
from fuzzywuzzy import fuzz
import pickle
import pandas as pd
import logging
import time
import requests
import codecs
from .send_message_vonage import *
logger = logging.getLogger(__name__)

# Load the dictionary from the pickle file
with open('base/intent_dict.pkl', 'rb') as file:
    intent_dict = pickle.load(file)

with codecs.open('base/intent_dict_es.pkl', 'rb') as file:
    intent_dict_es = pickle.load(file, encoding='latin1')

with open('base/azure_intent.pkl', 'rb') as file:
    azure_intent = pickle.load(file)

with open('base/dialog_eng_es.pickle', 'rb') as file:
    dialog_dict = pickle.load(file)

df = pd.read_excel('base/responses.xlsx',engine='openpyxl')


client = vonage.Client(key=settings.VONAGE_KEY, secret=settings.VONAGE_SECRET, timeout=10)
sms = vonage.Sms(client)

authenticator = IAMAuthenticator(settings.WATSON_API_KEY)
assistant = AssistantV2(version='2021-06-14',authenticator=authenticator)
assistant.set_service_url(f'https://api.us-south.assistant.watson.cloud.ibm.com')

# Create an authenticator using the API key
authenticator = IAMAuthenticator(settings.IBM_LANGUAGE_TRANSLATOR_API)
# Create an instance of the LanguageTranslatorV3 class with specified version and authenticator
language_translator = LanguageTranslatorV3(version='2018-05-01',authenticator=authenticator)
# Set the service URL for the language translator
language_translator.set_service_url(settings.IBM_LANGUAGE_TRANSLATOR_URL)


def get_datetime_now():
    # Add logging for getting the current datetime
    logger.info("Getting current datetime...")
    timezone_offset = -7.0  # UTC-07:00 Mountain Time Zone
    tzinfo = timezone(timedelta(hours=timezone_offset))
    datetime_now = datetime.now(tzinfo)
    logger.info(f"Current datetime: {datetime_now}")
    return datetime_now

def weekday_count(start, end):
    # Add logging for weekday counting
    logger.info("Counting weekdays...")
    week = {}
    for i in range((end - start).days):
        day = calendar.day_name[(start + timedelta(days=i + 1)).weekday()]
        week[day] = week[day] + 1 if day in week else 1
    logger.info(f"Weekday count: {week}")
    return week

def hours_between_dates(datetime1, datetime2, common_timezone='UTC'):
    # Add logging for calculating hours between dates
    logger.info("Calculating hours between dates...")
    tz = pytz.timezone(common_timezone)
    datetime1 = datetime1.astimezone(tz)
    datetime2 = datetime2.astimezone(tz)

    hour1 = datetime1.hour
    hour2 = datetime2.hour

    if hour2 >= hour1:
        hours_diff = hour2 - hour1
    else:
        hours_diff = (24 - hour1) + hour2

    logger.info(f"Hours between dates: {hours_diff}")
    return hours_diff



def send_to_watson_assistant(text):
    logger.info(f"Sending text to Watson Assistant: {text}")
    message_input = {
        'message_type': 'text',
        'text': text
    }
    try:
        result = assistant.message_stateless(settings.WATSON_ASSISTANT_ID, input=message_input).result['output']
        if result['intents']:
            intent = result['intents'][0]['intent']
            confidence = result['intents'][0]['confidence']
            logger.info(f"Received intent: {intent} with confidence: {confidence}")
        else:
            intent = 'None'
            confidence = 0
            logger.info("No intents returned from Watson Assistant")
    except Exception as e:
        intent = 'None'
        confidence = 0
        logger.error(f"Error while communicating with Watson Assistant: {str(e)}")
    return intent, confidence


def translate(text):
    try:
        # Detect the language of the input text
        language_detection = language_translator.identify(text).get_result()
        language = language_detection['languages'][0]['language']
        logger.info(f"Detected language: {language}")
        translated_text = None
        
        if language != 'en':
            # Translate the text from the detected language to English
            translation = language_translator.translate(
                text=text,
                source=language,
                target='en'
            ).get_result()
            
            # Extract the translated text from the API response
            translated_text = translation['translations'][0]['translation']
            text_to_classify = translated_text
        else:
            # If the language is already English, use the original text
            text_to_classify = text
        
        return text_to_classify, translated_text, language
    except ApiException as e:
        # Handle the 404 error here (model not found for specified languages)
        logger.error(f"Error while translating text: {str(e)}")
        # You can return a default translation or handle the error as needed
        return text, None, None  # Returning the original text and None for other values

    
def similarity_score(row, target_value):
    try:
        # Calculate the similarity score using the fuzzy string matching algorithm
        score = fuzz.ratio(row['intent'], target_value)
        # logger.info(f"Similarity score for '{row['intent']}' and '{target_value}': {score}")
        return score
    except Exception as e:
        logger.error(f"Error in similarity_score: {str(e)}")
        return 0

def remove_hyperlinks(text):
    try:
        # Define a regular expression pattern to match hyperlinks
        hyperlink_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'

        # Use the re.sub() function to replace hyperlinks with an empty string
        text_without_hyperlinks = re.sub(hyperlink_pattern, '', text)
        logger.info(f"Removed hyperlinks from text: {text}")
        return text_without_hyperlinks
    except Exception as e:
        logger.error(f"Error in remove_hyperlinks: {str(e)}")
        return text



# Find the domain for a given intent
def find_domain_for_intent(df, intent):
    try:
        row = df[df["intent"] == intent].iloc[0]
        domain = row["domain"]
        logger.info(f"Domain found for intent '{intent}': {domain}")
        return domain
    except IndexError:
        logger.warning(f"No intent found for '{intent}' in DataFrame.")
        return None
    except Exception as e:
        logger.error(f"Error finding domain for intent '{intent}': {e}")
        return None


# Get 4 random intents with the same domain as the given intent
def get_random_intents_with_same_domain(df, intent):
    domain = find_domain_for_intent(df, intent)
    
    if domain is not None:
        # Filter rows with the same domain, excluding the original intent
        domain_intents = df[(df["domain"] == domain) & (df["intent"] != intent)]
        
        if len(domain_intents) >= 4:
            # Randomly select 4 intents from the filtered domain_intents
            random_intents = random.sample(domain_intents["intent"].tolist(), 4)
            logger.info(f"Selected random intents with the same domain as '{intent}': {random_intents}")
            return random_intents
        else:
            logger.warning(f"Not enough intents with the same domain as '{intent}'.")
            return None
    else:
        return None



def clean_and_determine_text_number_or_stop(received_text):
    # Clean the received text by removing leading and trailing whitespace
    cleaned_text = received_text.strip()

    # Check if the cleaned text is a number
    if cleaned_text.isdigit():
        classification = "number"
    # Check if the cleaned text is "stop" (case-insensitive)
    elif cleaned_text.lower() == "stop":
        classification = "stop"
    elif cleaned_text.lower() == "heart" or cleaned_text.lower() == "yes":
        classification = "opt_in"
    # If the text doesn't match "number" or "stop," classify it as "other"
    else:
        classification = "other"
    
    # Log the cleaned text and its classification
    logger.info(f"Received text: '{received_text}' cleaned to: '{cleaned_text}', classified as: '{classification}'")

    return cleaned_text, classification


def convert_str_to_dict(str_to_convert):
    try:
        converted_dict = json.loads(json.loads(str_to_convert))              
    except:
        converted_dict = json.loads(str_to_convert)
    logger.info(f"Converted string to dictionary: {converted_dict}")
    return converted_dict


def process_number_input(received_text, phone_number):
    latest_picklist_entry = Picklist.objects.filter(phone_number=phone_number).latest('created_at')
    context = latest_picklist_entry.context
    language = latest_picklist_entry.language
    numbered_dialog = ""
    numbered_intents_dict = {}
    
    try:
        picklist_str = latest_picklist_entry.picklist
        picklist_dict = convert_str_to_dict(picklist_str)
        # Get the response for the specific key (number)
        try:
            key_value = picklist_dict.get(received_text)
        except:
            key_value = picklist_dict.get(int(received_text))

        logger.info(f"Generated response for key {received_text} from Picklist: {key_value}")
        # Update context response using an external function (defined elsewhere)
        response, numbered_dialog, numbered_intents_dict = update_context_response(received_text, context, key_value, phone_number,language)
        logger.info(f"Response generated: {response}")
    except json.JSONDecodeError as e:
        # Handle JSON decoding error
        logger.error(f"JSONDecodeError: {e}")
        response = "Invalid option selected"
    return response, numbered_dialog, numbered_intents_dict, language, context



def process_stop_input(received_text, phone_number):
    context = "stop"
    # Update the active field to False
    phone_number.active = False

    # Save the changes to the database
    phone_number.save()
    response = "You have successfully unsubscribed from the study. You will no longer receive any messages from us. Thank you for your participation!"
    
    # Log the unsubscribe action
    logger.info("Phone number unsubscribed.")
    logger.info(f"Response generated: {response}")
    return context, response


def generate_response(received_text, text_type, phone_number):
    context = ""
    numbered_intents_dict = {}
    language = ""
    numbered_dialog = ""
    response = ""

    if text_type == "number":   
        response, numbered_dialog, numbered_intents_dict, language, context = process_number_input(received_text, phone_number)
    elif text_type == "stop":
        context, response = process_stop_input(received_text, phone_number)
    elif text_type == "opt_in":
        response = "Thank you for opting in!"
        route = "opt_in_confirmation"
        phone_number.opted_in = True
        # send_message_vonage(response, phone_number, route)
        # TextMessage.objects.create(phone_number=phone_number, message=response, route=route)
    else:
        context = "regular"
        # Get a response based on the received text using an external function (defined elsewhere)
        response, numbered_dialog, numbered_intents_dict = get_response_for_text(received_text, phone_number)

    logger.info(f"Generated response for received text: '{received_text}', response: '{response}', context: '{context}', language: '{language}'")
    return response, numbered_dialog, numbered_intents_dict, language, context



def get_response_for_number_topic_selection(phone_number, integer_value,key_value):
    latest_weekly_topic = WeeklyTopic.objects.filter(phone_number=phone_number).latest('created_at')
    latest_weekly_topic.topic_id = integer_value
    latest_weekly_topic.save()
    logger.info(f"Updated topic ID for phone number {phone_number} to {integer_value}")
    topic = Topic.objects.get(id=integer_value)
    if phone_number.language == "es":
        response = f"¡Excelente! Has seleccionado {topic.name_es} como tema para esta semana. Le enviaremos información sobre {topic.name_es} durante los próximos 7 días."
    else:
        response = f"Great! You have selected {topic.name} as your topic for this week. We will send you information about {topic.name} for the next 7 days."
    logger.info(response)
    return response


def get_response_for_number_goal_setting(phone_number, integer_value,key_value):
    if phone_number.language == "es":
        response = f"¡Excelente! Has fijado tu objetivo. Nos comunicaremos con usted en unos días para ver cómo va."
    else:
        response = f"Great! You have set your goal to: '{key_value}'. We will check in with you in a few days to see how it's going."
    latest_goal_message = MessageTracker.objects.filter(phone_number=phone_number, sent_goal_message=True).latest('updated_at')
    latest_goal_message.set_goal = response
    latest_goal_message.save()
    logger.info(f"Updated goal message for phone number {phone_number} to: '{key_value}'")
    return response


def get_response_for_number_goal_feedback(phone_number,integer_value,key_value):
    latest_goal_feedback = MessageTracker.objects.filter(phone_number=phone_number,sent_goal_feedback_message=True).latest('updated_at')
    latest_goal_feedback.goal_feedback = key_value
    latest_goal_feedback.save()
    logger.info(f"Updated goal feedback for phone number {phone_number} to: '{key_value}'")
    if phone_number.language == "es":
        response = "¡Gracias por tus comentarios!"
    else:
        response = f"Thank you for your feedback!"
    return response

def get_response_for_number_language_selector(phone_number,integer_value,key_value):
    response = "¡Excelente! Ha seleccionado el español como idioma. A partir de ahora te enviaremos mensajes en español."
    response = response + "\n\n" + settings.WELCOME_MESSAGE_ES
    phone_number.language = "es"
    phone_number.save()
    return response

def get_response_regular_piclist(intent,language,phone_number):
    response, numbered_dialog, numbered_intents_dict = get_response_by_intent_language(intent,language,phone_number)
    return response, numbered_dialog, numbered_intents_dict

def get_response_by_intent_language(intent, language, phone_number):
    logger.info(f"get_response_by_intent_language called for intent: '{intent}' in {language} for phone number: {phone_number.id}")
    # Filter the DataFrame to get the rows with the specified intent
    filtered_df = df[df['intent'] == intent]

    if not filtered_df.empty:
        # Get the first row with the specified intent
        filtered_row = filtered_df.iloc[0]
        logger.info(f"Found intent '{intent}' in {language}.")
    else:
        temp_df = df.copy()
        # Apply similarity_score function to each row and create a new column
        temp_df['Similarity'] = temp_df.apply(lambda row: similarity_score(row, intent), axis=1)
        # Find the row with the highest similarity score
        filtered_row = temp_df[temp_df['Similarity'] == temp_df['Similarity'].max()].iloc[0]
        logger.warning(f"No intent found for {intent} in {language}! Using {filtered_row['intent']} instead.")
        logger.warning(f"Text similarity used to get intent for '{intent}' in {language}.")
    
    intent = filtered_row['intent']
    
    # Extract related intents from the filtered row
    related_intents = get_random_intents_with_same_domain(df, intent)
    related_dialog_en = [intent_dict[intent] for intent in related_intents]
    related_dialog_es = [intent_dict_es[intent] for intent in related_intents]
    
    # Create a dictionary of numbered intents and their related intent names
    numbered_intents_dict = {str(i + 1): intent for i, intent in enumerate(related_intents)}
    numbered_intents_dict = json.dumps(numbered_intents_dict)
    Picklist.objects.create(phone_number=phone_number, context='regular_picklist_response', picklist=str(numbered_intents_dict), language=language)
    logger.info(f"Picklist created for intent '{intent}' in {language}.") 
    
    if phone_number.language == "es":
        response = filtered_row['response_es']
        response_1 = filtered_row['response_1_es']
        numbered_dialog = '\n'.join([f'{i + 1}. {intent}' for i, intent in enumerate(related_dialog_es)])
        numbered_dialog = str(response_1) + '\n\n' + 'Pregúntame sobre otra cosa:\n' + str(numbered_dialog)

    elif language == 'en' or language =="":
        # Set the response and related intents for English language
        response = filtered_row['response']
        numbered_dialog = '\n'.join([f'{i + 1}. {intent}' for i, intent in enumerate(related_dialog_en)])
        numbered_dialog = 'Ask me about something else:\n' + str(numbered_dialog)
    else:
        # Set the response and related intents for non-English languages
        response = filtered_row['response_es']
        response_1 = filtered_row['response_1_es']
        numbered_dialog = '\n'.join([f'{i + 1}. {intent}' for i, intent in enumerate(related_dialog_es)])
        numbered_dialog = str(response_1) + '\n\n' + 'Pregúntame sobre otra cosa:\n' + str(numbered_dialog)

    logger.info(f"Response generated for intent '{intent}' in {language}.")
    return response, numbered_dialog, numbered_intents_dict



def update_context_response(integer_value, context, key_value, phone_number, language):
    numbered_intents_dict = {}
    numbered_dialog = ""
    logger.info(f"Updating context response for context: '{context}'")
    if context == "topic_selection":
        response = get_response_for_number_topic_selection(phone_number, integer_value,key_value)
    elif context == "goal_setting":
        response = get_response_for_number_goal_setting(phone_number, integer_value,key_value)
    elif context == "goal_feedback":
        response = get_response_for_number_goal_feedback(phone_number, integer_value,key_value)
    elif context == "language_selector":
        response = get_response_for_number_language_selector(phone_number, integer_value,key_value)
    else:
        response, numbered_dialog, numbered_intents_dict = get_response_regular_piclist(key_value, language, phone_number)
    
    logger.info(f"Updated context response for context: '{context}' with response: '{response}'")
    return response, numbered_dialog, numbered_intents_dict



def get_response_by_confidence(text, intent, confidence, language, phone_number):
    logger.info(f"get_response called for '{text}' with confidence {confidence}")
    numbered_dialog = ''
    if confidence > 0.75:
        response, numbered_dialog, numbered_intents_dict = get_response_by_intent_language(intent, language, phone_number)
    else:
        # If confidence is lower, get prediction-based response and empty numbered intents
        logger.info("Confidence too low, using model prediction")
        response, numbered_intents_dict = get_prediction_azure(text, language, phone_number)

    logger.info(f"Response for '{text}' with confidence {confidence}: '{response}'")
    return response, numbered_dialog, numbered_intents_dict



def get_response_for_text(received_text, phone_number):
    # Translate the received text and determine intent and confidence
    text_to_classify, translated_text, language = translate(received_text)
    intent, confidence = send_to_watson_assistant(text_to_classify)

    # Log the detected intent and confidence
    logger.info(f"Detected intent: '{intent}' with confidence: {confidence} for text: '{text_to_classify}'")

    # Get the response based on the intent and confidence
    response, numbered_dialog, numbered_intents_dict = get_response_by_confidence(text_to_classify, intent, confidence, language, phone_number)

    # Log the generated response
    logger.info(f"Generated response: '{response}'")

    # Create a Picklist entry for the numbered intents
    Picklist.objects.create(phone_number=phone_number, context='', picklist=str(numbered_intents_dict), language=language)

    return response, numbered_dialog, numbered_intents_dict



def get_prediction_render(text, language, phone_number):
    logger.info(f"get_prediction called for {text}")
    url = "https://text-classifier-blcz.onrender.com/c4hprediction"

    payload = json.dumps({"text_to_classify": text})

    headers = {"Content-Type": "application/json"}

    response = requests.request("POST", url, headers=headers, data=payload)
    response = json.loads(response.text)
    top_intents = response.get('prediction')
    numbered_intents_dict = {str(i + 1): intent for i, intent in enumerate(top_intents)}
    numbered_intents_dict = json.dumps(numbered_intents_dict)
    Picklist.objects.create(phone_number=phone_number, context='', picklist=str(numbered_intents_dict), language=language)

    # Get the corresponding probabilities
    if language == 'en':
        top_dialogs = [intent_dict[intent] for intent in top_intents]
        response_text = 'Are you asking about: \n' + ('\n'.join([f'{i + 1}. {intent}' for i, intent in enumerate(top_dialogs)]))
    else:
        top_dialogs = [intent_dict_es[intent] for intent in top_intents]
        response_text = '¿Estás preguntando sobre: \n' + ('\n'.join([f'{i + 1}. {intent}' for i, intent in enumerate(top_dialogs)]))
    
    # Log the model prediction results
    logger.info(f"Model prediction used for {text}. Top intents: {top_intents}")
    
    return response_text, numbered_intents_dict

def get_prediction_azure(text, language, phone_number):
    logger.info(f"get_prediction called for {text}")
    url = "https://clinic-chat-test.cognitiveservices.azure.com/language/:analyze-conversations?api-version=2022-10-01-preview"

    headers = {
        "Ocp-Apim-Subscription-Key": "f0786e002e9d4917b4af22bdf22e6dc3",
        "Apim-Request-Id": "4ffcac1c-b2fc-48ba-bd6d-b69d9942995a",
        "Content-Type": "application/json"
    }

    participant_id = "1"
    query_language = "en"

    data = {
    "kind": "Conversation",
    "analysisInput": {
        "conversationItem": {
            "id": participant_id,
            "text": text,
            "modality": "text",
            "language": query_language,
            "participantId": participant_id
        }
    },
    "parameters": {
        "projectName": "Chat4HeartHealth",
        "verbose": True,
        "deploymentName": "Chat4HeartHealth",
        "stringIndexType": "TextElement_V8"
    }
}

    response = requests.post(url, headers=headers, json=data)
    top5intents_json = response.json()['result']['prediction']['intents'][:5]
    topazure_intents = [i['category'] for i in top5intents_json]
    topazure_intents = [s[:45] for s in topazure_intents]
    top_intents = [azure_intent[i] for i in topazure_intents if i in azure_intent]
    numbered_intents_dict = {str(i + 1): intent for i, intent in enumerate(top_intents)}
    numbered_intents_dict = json.dumps(numbered_intents_dict)
    Picklist.objects.create(phone_number=phone_number, context='', picklist=str(numbered_intents_dict), language=language)

    # Get the corresponding probabilities
    if language == 'en':
        top_dialogs = [intent_dict[intent] for intent in top_intents]
        response_text = 'Are you asking about: \n' + ('\n'.join([f'{i + 1}. {intent}' for i, intent in enumerate(top_dialogs)]))
    else:
        top_dialogs = [intent_dict_es[intent] for intent in top_intents]
        response_text = '¿Estás preguntando sobre: \n' + ('\n'.join([f'{i + 1}. {intent}' for i, intent in enumerate(top_dialogs)]))
    
    # Log the model prediction results
    logger.info(f"Model prediction used for {text}. Top intents: {top_intents}")
    
    return response_text, numbered_intents_dict