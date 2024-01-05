import logging
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import register_events, register_job
from .scheduled_content import *
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError
from django.conf import settings


logger = logging.getLogger(__name__)

def start():
    try:
        scheduler = BackgroundScheduler(settings.SCHEDULER_CONFIG, job_defaults={'max_instances': 1, 'misfire_grace_time': 150})
        jobs = [
            (send_topic_selection_message, 'Send Topic Selection Message',CronTrigger(hour=9, minute=0)),

            (send_scheduled_message, 'Send Scheduled Info Message',CronTrigger(hour=10, minute=0)),
            (send_goal_message, 'Send Goals Message',CronTrigger(hour=9, minute=15)),
            (send_goal_feedback, 'Send Goals Feedback Message',CronTrigger(hour=9, minute=30)),
            (send_final_pilot_message, 'Send Final Pilot Message',CronTrigger(hour=17, minute=0))
        ]
        for job in jobs:
            scheduler.add_job(job[0], id=job[1], replace_existing=True, trigger=job[2], coalesce=True)
        register_events(scheduler)
        scheduler.start()
        logger.info('Scheduler started successfully')
    except Exception as e:
        logger.error(f'Error starting scheduler: {e}')