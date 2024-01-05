from .models import PhoneNumber, Arm, ScheduledMessage, TextMessage, Topic, WeeklyTopic, TopicGoal, MessageTracker, Picklist, ScheduledMessageControl
from django.db.models import Q
from django.conf import settings
from datetime import datetime, timezone, timedelta
import logging
from .helper_functions import *
from .send_message_vonage import *
import json
import pickle
import codecs
import time
import pytz



logger = logging.getLogger(__name__)

values_to_filter = ["Healthy Eating","Getting Active","Healthy Sleep","Managing Weight"]

# with codecs.open('base/dialog_eng_es.pickle', 'rb') as file:
#     dialog_dict = pickle.load(file, encoding='latin1')


# def get_week_num_andcurrent_weekday(created_at):
#     print(type(created_at))
#     timezone_offset = -7.0  # UTC-07:00 Mountain Time Zone
#     tzinfo = timezone(timedelta(hours=timezone_offset))
#     now = datetime.now(tz=created_at.tzinfo)
#     print(type(now))
#     week_num = now.hour - created_at.hour
#     current_weekday = (now.minute // 11)%5
#     if current_weekday == 0:
#         current_weekday = 5
#     logger.info(f"week_num: {week_num},current_weekday: {current_weekday} for {created_at} and {now}")
#     return week_num, current_weekday

def get_week_num_andcurrent_weekday(created_at):
    mst = timezone(timedelta(hours=-7))
    # Convert the datetime to MST
    created_at = created_at.astimezone(mst)
    # Get current datetime in UTC
    now_utc = datetime.now(pytz.utc)
    # Convert current datetime to the timezone of created_at
    now_in_created_at_tz = now_utc.astimezone(created_at.tzinfo)
    # Calculate the difference in days
    total_days = (now_in_created_at_tz.date() - created_at.date()).days    
    if total_days <= 0:
        return 0, 0
    else:
        week_num = total_days // 5 + 1
        current_weekday = total_days % 5
        if current_weekday == 0:
            week_num -= 1
            current_weekday = 5
        return week_num, current_weekday

# def get_week_num(created_at):
    
#     timezone_offset = -7.0  # UTC-07:00 Mountain Time Zone
#     tzinfo = timezone(timedelta(hours=timezone_offset))
#     now = datetime.now(tz=created_at.tzinfo)
#     week_num = now.hour - created_at.hour
#     logger.info(f"week_num: {week_num} for {created_at} and {now}")
#     return week_num

def get_week_num(created_at):
    # Get current datetime in UTC
    now_utc = datetime.now(pytz.utc)
    
    # Convert current datetime to the timezone of created_at
    now_in_created_at_tz = now_utc.astimezone(created_at.tzinfo)
    
    # Calculate the difference in days
    total_days = (now_in_created_at_tz - created_at).days
    if total_days <= 0:
        return 0
    else:
        week_num = total_days // 5 + 1
    return week_num


def send_topic_selection_message():
    phone_numbers = PhoneNumber.objects.filter(arm__name__icontains="control")
    logger.info(f'Found {phone_numbers.count()} phone numbers with arm name control')
    for phone_number in phone_numbers:
        week_num,current_weekday = get_week_num_andcurrent_weekday(phone_number.created_at)

        if week_num > int(4):
            logger.info(f'Skipping {phone_number.id} because it is week {week_num}')
            continue
        if current_weekday != int(1):
            logger.info(f'Skipping {phone_number.id} because it is weekday {current_weekday}')
            continue
        if phone_number.sub_group:
            topic_num = week_num*2
        else:
            topic_num = week_num*2-1
        try:
            if MessageTracker.objects.filter(phone_number=phone_number, week_no=week_num)[0]:
                logger.info(f'Skipping {phone_number.id} because topic already assigned for week {week_num}')
                continue
        except IndexError:
            pass
        logger.info(f"Assigning topic number {topic_num} to {phone_number.id}")
        WeeklyTopic.objects.create(phone_number=phone_number, topic_id=topic_num, week_number=week_num)
        logger.info(f"Updated message tracker for {phone_number.id}")
        MessageTracker.objects.update_or_create(phone_number=phone_number,week_no = week_num,defaults={'sent_topic_selection_message': False})
    phone_numbers = PhoneNumber.objects.filter(arm__name__icontains="ai_chat")
    logger.info(f'Found {phone_numbers.count()} phone numbers with arm name ai_chat')
    for phone_number in phone_numbers:
        try:
            if not phone_number.active:
                continue
            # day_count_dict = weekday_count(phone_number.created_at,get_datetime_now())
            week_num,current_weekday = get_week_num_andcurrent_weekday(phone_number.created_at)
            logger.info(f"Current hour for {phone_number.id}: {week_num}")
            if week_num > int(4) or week_num <= 0:
                logger.info(f'Skipping {phone_number.id} because it is week {week_num}')  
                continue
            if current_weekday != int(1):
                logger.info(f'Skipping {phone_number.id} because it is weekday {current_weekday}')
                continue
            try:
                if MessageTracker.objects.filter(phone_number=phone_number,week_no=week_num)[0].sent_topic_selection_message:
                    logger.info(f'Skipping {phone_number.id} because topic selection message already sent for week {week_num}')
                    continue
            except:
                pass
            topics_in_weekly_topic = WeeklyTopic.objects.filter(phone_number=phone_number).values_list('topic__id', flat=True)
            logger.info("fetched already completed topics")
            topics_not_in_weekly_topic = Topic.objects.exclude(id__in=topics_in_weekly_topic)
            exclude_condition = Q(id__in=topics_in_weekly_topic)
            if phone_number.sub_group:
                actual_topics = Topic.objects.filter(name__in=values_to_filter)
            else:
                actual_topics = Topic.objects.exclude(name__in=values_to_filter)
            topics_not_in_weekly_topic = actual_topics.exclude(exclude_condition)
            if  phone_number.language == 'es':
                topic_info_not_in_weekly_topic = topics_not_in_weekly_topic.values('id', 'name_es')
                picklist = {str(topic_info['id']): topic_info['name_es'] for topic_info in topic_info_not_in_weekly_topic}
                default_topic_id = min(picklist.keys())
                default_topic_name = picklist[default_topic_id]
                pre_message = f'Hola, Chat del Corazón le enviará mensajes en los próximos días sobre una {default_topic_name}. Si prefiere un tema diferente, escriba el número del tema que prefiere de esta lista:\n'
                if topic_info_not_in_weekly_topic.count()<=1:
                    pre_message = f'Hola, Chat del Corazón le enviará mensajes en los próximos días sobre una {default_topic_name}.\n'
                    message = ""
                else:
                    pre_message = f'Hola, Chat del Corazón le enviará mensajes en los próximos días sobre una {default_topic_name}. Si prefiere un tema diferente, escriba el número del tema que prefiere de esta lista:\n'
                    message = '\n'.join([f"{topic_id}. {topic_name}" for topic_id, topic_name in picklist.items() if topic_id != min(picklist.keys())])
                message = pre_message + message
            else:
                topic_info_not_in_weekly_topic = topics_not_in_weekly_topic.values('id', 'name')
                picklist = {str(topic_info['id']): topic_info['name'] for topic_info in topic_info_not_in_weekly_topic}
                default_topic_id = min(picklist.keys())
                default_topic_name = picklist[default_topic_id]
                
                if topic_info_not_in_weekly_topic.count()<=1:
                    pre_message = f'Hi, Chat 4 Heart Health is sending you messages over the next few days about {default_topic_name}.\n'
                    message = ""
                else:
                    pre_message = f'Hi, Chat 4 Heart Health is sending you messages over the next few days about {default_topic_name}. If you prefer a different topic, write the number of the topic you prefer from this list:\n'
                    message = '\n'.join([f"{topic_id}. {topic_name}" for topic_id, topic_name in picklist.items() if topic_id != min(picklist.keys())])
                message = pre_message + message
            picklist_json = json.dumps(picklist)
            retry_send_message_vonage(message,phone_number, route='outgoing_scheduled_topic_selection')
            WeeklyTopic.objects.create(phone_number=phone_number, topic_id=default_topic_id, week_number=week_num)
            Picklist.objects.create(phone_number=phone_number, context='topic_selection', picklist=picklist_json)
            TextMessage.objects.create(phone_number=phone_number, message=message, route='outgoing_scheduled_topic_selection')
            MessageTracker.objects.update_or_create(phone_number=phone_number,week_no = week_num,defaults={'sent_topic_selection_message': True})
            logger.info(f"Sent topic selection message to {phone_number.id} at {datetime.now()}")
        except Exception as e:
            logger.error(f"Error sending topic selection message to {phone_number.id}: {e}")


def send_scheduled_message():
    phone_numbers = PhoneNumber.objects.filter(Q(arm__name__icontains="ai_chat") | Q(arm__name__icontains="control"))
    logger.info(f'Found {phone_numbers.count()} phone numbers')
    for phone_number in phone_numbers:
        try:
            if not phone_number.active:
                continue
            week_num,current_weekday = get_week_num_andcurrent_weekday(phone_number.created_at)
            logger.info(f"Current week for {phone_number.id}: {week_num}")
            if week_num <= 0 or week_num > int(4):
                logger.info(f'Skipping {phone_number.id} because it is week {week_num}')
                continue
            logger.info("fetching weekly_topic_id")
            weekly_topic_id = WeeklyTopic.objects.filter(phone_number=phone_number,week_number=week_num)[0].topic_id
            logger.info(f"weekly_topic_id: {weekly_topic_id}")
            if phone_number.arm.name.lower().find("ai_chat") != -1:
                scheduled_messages = ScheduledMessage.objects.filter(topic_id=weekly_topic_id,weekday=current_weekday)
            else:
                scheduled_messages = ScheduledMessageControl.objects.filter(topic_id=weekly_topic_id,weekday=current_weekday)
            logger.info("fetched scheduled_messages")
            if not scheduled_messages:
                logger.info(f'No scheduled messages found for topic {weekly_topic_id} and weekday {current_weekday}')
                continue
            message_tracker_col = f'sent_info_message_{current_weekday}'
            message_tracker = MessageTracker.objects.filter(phone_number=phone_number, week_no=week_num)[0]
            logger.info(f"message tracker column to be updated: {message_tracker_col}")
            if getattr(message_tracker, message_tracker_col):
                logger.info(f'Skipping {phone_number.id} because scheduled info message was sent for week {week_num} and day {current_weekday}')
                continue
            scheduled_message = scheduled_messages[0]
            if phone_number.language == 'es':
                message = scheduled_message.message_es
            else:
                message = scheduled_message.message
            logger.info(f"scheduled message: {message[:20]}")
            if phone_number.arm.name.lower().find("ai_chat") != -1:
                picklist = scheduled_message.picklist
                picklist_json = json.dumps(picklist)
                logger.info(f"picklist_json: {picklist_json}")
                Picklist.objects.create(phone_number=phone_number, context='regular_picklist', picklist=picklist_json)
                logger.info(f"language: {phone_number.language}")
                if phone_number.language == 'es':
                    numbered_dialog = '\n'.join([f"{i}. {dialog_dict[dialog]}" for i, dialog in convert_str_to_dict(picklist_json).items()])
                    logger.info(f"numbered_dialog es: {numbered_dialog}")
                else:
                    numbered_dialog = '\n'.join([f"{i}. {dialog}" for i, dialog in convert_str_to_dict(picklist_json).items()])
                    logger.info(f"numbered_dialog: {numbered_dialog}")
                message = message + '\n' + numbered_dialog
            else:
                message = message
            if not getattr(message_tracker, message_tracker_col):
                retry_send_message_vonage(message,phone_number, route='outgoing_scheduled_info')
                TextMessage.objects.create(phone_number=phone_number, message=message, route='outgoing_scheduled_info')
                setattr(message_tracker, message_tracker_col, True)
            message_tracker.save()
            logger.info(f"Sent info message to {phone_number.id} for day {week_num} for topic {weekly_topic_id}")
            time.sleep(10)
        except Exception as e:
            logger.error(f"Error sending scheduled message to {phone_number.id}: {e}")

def send_goal_message():
    phone_numbers = PhoneNumber.objects.filter(arm__name__icontains="ai_chat")
    logger.info(f'Found {phone_numbers.count()} phone numbers with arm name ai_chat')
    for phone_number in phone_numbers:
        try:
            if not phone_number.active:
                continue
            week_num,current_weekday = get_week_num_andcurrent_weekday(phone_number.created_at)
            logger.info(f"Current weekday for {phone_number.id}: {week_num}")
            if week_num <= 0 or week_num > int(4):
                logger.info(f'Skipping {phone_number.id} because it is week {week_num}')
                continue
            if current_weekday != int(2):
                logger.info(f'Skipping {phone_number.id} because it is not day {current_weekday}')
                continue
            if MessageTracker.objects.filter(phone_number=phone_number,week_no=week_num)[0].sent_goal_message:
                logger.warning(f'Skipping {phone_number.id} because goal message sent for week {week_num}')
                continue
            weekly_topic_id = WeeklyTopic.objects.filter(phone_number=phone_number,week_number=week_num)[0].topic_id
            topic_goals = TopicGoal.objects.filter(topic_id=weekly_topic_id)
            if not topic_goals:
                logger.error(f'No goals found for topic {weekly_topic_id}')
                continue
            topic_goal = topic_goals[0]
            if phone_number.language == 'es':
                message = topic_goal.goal_es
            else:
                message = topic_goal.goal
            picklist = topic_goal.goal_dict            
            logger.info(f"Sent goals message to {phone_number.id} for topic {weekly_topic_id}")
            picklist_json = json.dumps(picklist)
            MessageTracker.objects.update_or_create(phone_number=phone_number,week_no = week_num,defaults={'sent_goal_message': True})
            Picklist.objects.create(phone_number=phone_number, context='goal_setting', picklist=picklist_json)
            retry_send_message_vonage(message,phone_number, route='outgoing_goal_setting')
            TextMessage.objects.create(phone_number=phone_number, message=message, route='outgoing_goal_setting')
        except Exception as e:
            logger.error(f"Error sending goal message to {phone_number.id}: {e}") 

def send_goal_feedback():
    phone_numbers = PhoneNumber.objects.filter(arm__name__icontains="ai_chat")
    logger.info(f'Found {phone_numbers.count()} phone numbers with arm name ai_chat')
    for phone_number in phone_numbers:
        try:
            if not phone_number.active:
                continue
            week_num,current_weekday = get_week_num_andcurrent_weekday(phone_number.created_at)
            logger.info(f"Current weekday for {phone_number.id}: {week_num}")
            if week_num <= 0 or week_num > int(4):
                logger.info(f'Skipping {phone_number.id} because it is week {week_num}')
                continue
            if current_weekday != int(5):
                logger.info(f'Skipping {phone_number.id} because it is weekday {current_weekday}')
                continue
            if MessageTracker.objects.filter(phone_number=phone_number,week_no=week_num)[0].sent_goal_feedback_message:
                logger.warning(f'Skipping {phone_number.id} because goal feedback message sent for week {week_num}')
                continue
            weekly_topic_id = WeeklyTopic.objects.filter(phone_number=phone_number,week_number=week_num)[0].topic_id
            topic_goals = TopicGoal.objects.filter(topic_id=weekly_topic_id)
            if not topic_goals:
                logger.error(f'No goals found for topic {weekly_topic_id}')
                continue
            topic_goal = topic_goals[0]
            if phone_number.language == 'es':
                message = topic_goal.goal_feedback_es
            else:
                message = topic_goal.goal_feedback
            picklist = topic_goal.goal_feedback_dict
            retry_send_message_vonage(message,phone_number, route='outgoing_goal_feedback')
            TextMessage.objects.create(phone_number=phone_number, message=message, route='outgoing_goal_feedback')
            logger.info(f"Sent goals feedback message to {phone_number.id} for topic {weekly_topic_id}")
            picklist_json = json.dumps(picklist)
            MessageTracker.objects.update_or_create(phone_number=phone_number,week_no = week_num,defaults={'sent_goal_feedback_message': True})
            Picklist.objects.create(phone_number=phone_number, context='goal_feedback', picklist=picklist_json)
        except Exception as e:
            logger.error(f"Error sending goal feedback message to {phone_number.id}: {e}")

final_message = "Denver Health thanks you for being a part of Chat 4 Heart Health! Feel free to keep chatting with us about healthy habits. Please take a few minutes now to complete this quick follow-up survey about your health."
def send_final_pilot_message():
    phone_numbers = PhoneNumber.objects.filter(Q(arm__name__icontains="ai_chat") | Q(arm__name__icontains="control"))
    logger.info(f'Found {phone_numbers.count()} phone numbers')
    for phone_number in phone_numbers:
        try:
            if not phone_number.active:
                continue
            week_num,current_weekday = get_week_num_andcurrent_weekday(phone_number.created_at)
            logger.info(f"Current weekday for {phone_number.id}: {week_num}")
            if week_num != int(5):
                logger.info(f'Skipping {phone_number.id} because it is week {week_num}')
                continue
            if phone_number.final_pilot_message_sent:
                logger.warning(f'Skipping {phone_number.id} because final message already sent')
                continue
            retry_send_message_vonage(final_message,phone_number, route='outgoing_final_message')
            TextMessage.objects.create(phone_number=phone_number, message=final_message, route='outgoing_final_message')
            time.sleep(10)
            try:
                post_survey_link = phone_number.post_survey
                retry_send_message_vonage(post_survey_link,phone_number, route='outgoing_post_survey_link')
                TextMessage.objects.create(phone_number=phone_number, message=post_survey_link, route='outgoing_post_survey_link')
            except:
                pass
            logger.info(f"Sent final message to {phone_number.id}")
            phone_number.final_pilot_message_sent = True
            phone_number.save()
        except Exception as e:
            logger.error(f"Error sending final message to {phone_number.id}: {e}")