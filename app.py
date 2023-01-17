from celery import Celery
import celery as clr
from celery.result import AsyncResult
import socket
import sys
from src import *
from src.settings import *
import pandas as pd
import os
import re
from dateutil.parser import parse


app = Flask(__name__,
            static_url_path='', 
            static_folder='static',
            template_folder='static/templates')

#Initialize celery
celery = Celery(app.name)
celery.conf.update(
    result_backend = CELERY_RESULT_BACKEND,
    broker_url = CELERY_BROKER_URL,
    timezone = CELERY_TIMEZONE,
    task_serializer = CELERY_TASK_SERIALIZER,
    accept_content = CELERY_ACCEPT_CONTENT,
    result_serializer = CELERY_RESULT_SERIALIZER,
    tasks_routes = CELERY_TASK_ROUTES,
)

#### POST request task ########################################################################

@celery.task(name = 'youtube_download', queue=QUEUE)
def youtube_download_post(params):
    """
    simple procedure of async task for downloading audio from youtube
    """
    
    go_on = False
    ## Logging ################################################################################
    logger = logger_init(f"{datetime.now().strftime('%Y%W')}_youtube_download",\
                         main_dirs['LOGS'])
    log(logger, 'init task', 'warn', f"Received next params: {params}")
    ## DB Redis instance ########################################################################
    try:
        db_redis = DBredis(
            topic = configs['REDIS__DB_STATUS'],
            host = REDIS_HOST,
            port = REDIS_PORT,
        )
        go_on = db_redis.publish_message(params['key'], 'busy') 
    except Exception as err:
        log(logger, 'init redis', 'error', f"Init redis during async task: {err}")
    ##############################################################################################
    
    if go_on:
        ##### preparation by parameteres -----------------------------------------------
        ## bitrate 
        yt_opts['options']['postprocessors'][0]['preferredquality'] = str(params['bitrate'])
        try:
            result = download_audio(params['links'], main_dirs['DATA'], **yt_opts['options'])
            if result == {}:
                go_on = False
                log(logger, 'downloading', 'error', f"Some internal problem during execution : {params['links']}")
            else:
                log(logger, 'downloading', 'info', f"Received next files after execution : {result.values()}")
        except (Exception) as err:
            log(logger, 'downloading', 'error', f"Exception during execution : {err}")
    
    if go_on:
        ##### cloud connector init -----------------------------------------------------
        cloud = Cloudmega(
            logger = logger,
            username = configs['MEGACLOUD__USER'],
            password = configs['MEGACLOUD__PASSW'])
        cloud.dir_name = params['fpath']
        go_on = cloud.mkdir(params['fpath'])
    
    if go_on:
        #-------------------------------------------------------------------------------
        for _, fpath in result.items():
            ### clean from symbols -----------------------------------------------
            fpath_ = clean_string(fpath)
            
            ### translit to english ----------------------------------------------
            fpath_ = translit(fpath_)

            ### clean from non english symbols -----------------------------------
            fpath_ = strip_non_english(fpath_).replace(' ', '_')

            ### rename fpath -----------------------------------------------------
            os.rename(fpath, fpath_)
            cloud.log('renaming file', 'info', f'File renamed: {fpath_}')

            #---------------------------------------------------------------------
            for _ in range(2):
                go_on = cloud.upload_file_to_cloud(fpath_)
                if go_on: break
                sleep(18)
            #---------------------------------------------------------------------
            os.remove(fpath_)
            if go_on: 
                cloud.log('uploading file', 'info', f'Succeeded in uploading {fpath_} into {cloud.dir_name}')
            else:
                cloud.log('uploading file', 'error', f'Problem in uploading {fpath_} into {cloud.dir_name}')
    else:
        log(logger, 'downloading', 'error', f"Problem with creating path : {params['fpath']}")

    go_on = db_redis.publish_message(params['key'], 'free')

#########################################################################################################################

@app.route('/', methods=['GET'])
def index():
    """

    """

    ## Logging ##########################################################
    logger = logger_init(f"{datetime.now().strftime('%Y%W')}_youtube_download",\
                         main_dirs['LOGS'])
    
    ## DB Redis #########################################################
    db_redis = DBredis(
                topic = configs['REDIS__DB_STATUS'],
                host = REDIS_HOST,
                port = REDIS_PORT)
    
    ## Initialize variables ############################################
    #authorized, queue_free, int_token, set_cookie = False, False, None, False
    app_engine = AppEngine(logger = logger, request = request, redisdb = db_redis)
    
    #  Parsing cookie with internal token ------------------------------
    app_engine.auth_process(token = configs['APIBOT_TOKEN'])
    
    #  check Redis status for queue availability -----------------------
    if app_engine.authorized:
        app_engine.check_status()
        
    ### if authorized and first visit - set cookie with internal token
    app_engine.create_response('index.html', 'Youtube Downloader')
    
    return app_engine.response


@app.route('/parse', methods=['POST'])
def process_request():
    """

    """
    
    ## Logging ##########################################################
    logger = logger_init(f"{datetime.now().strftime('%Y%W')}_youtube_download",\
                         main_dirs['LOGS'])
    
    ## DB Redis #########################################################
    db_redis = DBredis(
                topic = configs['REDIS__DB_STATUS'],
                host = REDIS_HOST,
                port = REDIS_PORT)
    
    ### Initialize variables ###########################################
    app_engine = AppEngine(logger = logger, request = request, redisdb = db_redis)

    #  Parsing cookie with internal token ------------------------------
    app_engine.auth_process(main_page = False)
    
    #  check Redis status for queue availability -----------------------
    if app_engine.authorized:
        app_engine.check_status()
        
    ### Parsing POST params --------------------------------------------
    app_engine.parse_post_params()
    
    if all([app_engine.parse_post, app_engine.queue_free]) and \
        app_engine.params_task['kind'] == 'youtube' and \
        not app_engine.uncorrect:
        
        taskss = youtube_download_post.delay(app_engine.params_task)
        task_id = taskss.id
        if task_id: app_engine.queue_start = True

        app_engine.log('Runing async task', 'info', f"Started task with task id {taskss.id} for {app_engine.params_task['kind']}.")
    elif app_engine.parse_post and \
        app_engine.params_task['kind'] == 'youtube' and \
        not app_engine.queue_free:

        app_engine.log('trying async task', 'error', f"The queue is busy for {app_engine.params_task['kind']}.")
    elif app_engine.parse_post and \
        app_engine.params_task['kind'] == 'youtube' and \
        not app_engine.uncorrect:

        app_engine.log('trying async task', 'error', f"Some parameters are not correct for {app_engine.params_task['kind']}.")
    
    #################################################################################################

    app_engine.create_response('index.html', 'Youtube Downloader')
        
    return app_engine.response


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=configs['API_PORT'], debug = True)