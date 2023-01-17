import os
import yaml
from pydantic import BaseSettings
from celery.schedules import crontab
from datetime import datetime, timedelta


QUEUE = 'main'

### main directories ###############################################################################
main_dirs = {}
#os.chdir('../')
main_dirs['ROOT'] = os.getcwd()
main_dirs['DATA'] = os.path.join(main_dirs['ROOT'], 'data')
main_dirs['LOGS'] = os.path.join(main_dirs['ROOT'], 'log')

for k,v in main_dirs.items():
    if k == 'ROOT':continue
    elif not os.path.exists(v):
        os.makedirs(v)

## getting params for using youtube library #######################################################
with open(os.path.join(main_dirs['ROOT'], 'src','youtube.yaml')) as f:
    yt_opts = yaml.load(f, Loader=yaml.Loader)

### Main credentials ###############################################################################
class Settings(BaseSettings):
    
    ### for cloud (MEGA)
    MEGACLOUD__USER: str = 'login'
    MEGACLOUD__PASSW: str = 'passw'
    timezone: str = 'Europe/London'

    ### email settings
    MAIL__USER: str = 'login'
    MAIL__USER_SEND: str = 'alex_bot-s'
    MAIL__FROM_SEND: str = 'email'
    MAIL__PASSW: str = 'secret'
    MAIL__INPUT_DOMAIN: str = 'pop3.mail'
    MAIL__OUTPUT_DOMAIN: str = 'smtp.mail'

    ### redis settings
    REDIS__HOST: str = 'localhost'
    REDIS__PORT: int = 6379
    REDIS__USER: str = ''
    REDIS__PASSW: str = ''
    REDIS__DB: int = 3
    REDIS__DB_STATUS: int = 11

    ##token for API
    APIBOT_TOKEN: str = 'secret'
    API_PORT: int = 5009
    FLOWER_PORT: int = 5555

    class Config:
        env_file = "./.env"
        env_file_encoding = 'utf-8'

#Loading auth configs
configs = Settings().dict()

REDIS_HOST = configs['REDIS__HOST']
REDIS_PORT = configs['REDIS__PORT']
REDIS_DB = configs['REDIS__DB']
BROKER_URL = os.environ.get('REDIS_URL', f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")

#CELERY
CELERY_BROKER_URL = BROKER_URL
CELERY_RESULT_BACKEND = BROKER_URL
CELERY_TIMEZONE = configs['timezone']
CELERY_ACCEPT_CONTENT = ['json', 'msgpack', 'yaml']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TASK_ROUTES = {
    'youtube_task':{'queue':QUEUE},
}

template_logs = '$date - [$type] : resource - $source, Data - [$kind]: $msg\n'