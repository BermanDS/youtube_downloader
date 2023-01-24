import os
import re
import gc
import sys
import uuid
import json
import redis
import string
import socket
import random
import logging
import youtube_dl
import pandas as pd
from mega import Mega
from time import time, sleep
from importlib import reload
from dateutil.parser import parse
from psutil._common import bytes2human
from datetime import datetime, timedelta, date, timezone
from flask import (
                    Flask,
                    Response,
                    render_template,
                    make_response,
                    request,
                    json,
                    jsonify
                    )

class NpEncoder(json.JSONEncoder):
    """ Custom encoder for numpy data types """
    
    def default(self, obj):
        if isinstance(obj, (np.int_, np.intc, np.intp, np.int8,
                            np.int16, np.int32, np.int64, np.uint8,
                            np.uint16, np.uint32, np.uint64)):

            return int(obj)

        elif isinstance(obj, (np.float_, np.float16, np.float32, np.float64)):
            return float(obj)

        elif isinstance(obj, (np.complex_, np.complex64, np.complex128)):
            return {'real': obj.real, 'imag': obj.imag}

        elif isinstance(obj, (np.ndarray,)):
            return obj.tolist()

        elif isinstance(obj, (np.bool_)):
            return bool(obj)

        elif isinstance(obj, (np.void)): 
            return None
        
        elif isinstance(obj, datetime):
            return obj.isoformat()
        
        return json.JSONEncoder.default(self, obj)

###################################################################################################
### Logging
###################################################################################################

log_levels = ["debug", "info", "warn", "error"]

def logger_init(service_name: str = '', log_path: str = os.getcwd(), log_level: str = 'info') -> object:
    """
    initialization of logger
    """

    reload(logging)
    service_name = service_name if service_name != '' else socket.gethostname()

    logging.basicConfig(
            filename = os.path.join(log_path, f'{service_name}.log'),
            level = logging.INFO if log_level == 'info' \
                    else logging.ERROR if log_level == 'error' \
                    else logging.WARN if log_level == 'warn' \
                    else logging.DEBUG,
        )
    return logging.getLogger(service_name)


def log(logger: object = None, tag: str = 'action-service', log_level: str = 'info', message: str = '', data: dict = {}) -> None:
    """
    logging with custom format:
    tag - some tag of action
    message - message for logging
    data - some key-value pairs for additional data of logging
    """

    if log_levels.index(log_level) >= log_levels.index(log_level) and logger:
        log_info = {
            "level": log_level,
            "time": datetime.now(timezone.utc).isoformat(),
            "tag": tag,
            "message": message,
        }
        log_info.update(data)
            
        if log_level == 'info': logger.info(json.dumps(log_info, cls=NpEncoder))
        elif log_level == 'debug':logger.debug(json.dumps(log_info, cls=NpEncoder))
        elif log_level == 'warn': logger.warn(json.dumps(log_info, cls=NpEncoder))
        elif log_level == 'error':logger.error(json.dumps(log_info, cls=NpEncoder))

####################################################################################################
#### connectors 
#####################################################################################################

class Cloudmega:
    """
    connection for uploading files to mega
    """

    def __init__(self, 
                logger: object = None,
                username: str = '', 
                password: str = '', 
                dir_name: str = '',
                start_date_of_files: object = None, 
                end_date_of_files: object = None):
        
        self.user = username
        self.domain = 'mega'
        self.password = password
        self.start_fdate = start_date_of_files
        self.end_fdate = end_date_of_files
        self.dir_name = dir_name
        self.dir_id = None
        self.dir_size = 0
        self.df_files = pd.DataFrame(columns = ['fname','size', 'fdate'])
        self.mega = None
        self.pref_msg = ''
        self.conn = None
        self.log_levels = ["debug", "info", "warn", "error"]
        self.logger = logger
        self.stat_info = None

    
    def log(self, tag: str = 'action-service', log_level: str = 'info', message: str = '', data: dict = {}):
        """
        logging with custom format:
        tag - some tag of action
        message - message for logging
        data - some key-value pairs for additional data of logging
        """

        if self.log_levels.index(log_level) >= self.log_levels.index(log_level) and self.logger:
            log_info = {
                "level": log_level,
                "time": datetime.now(timezone.utc).isoformat(),
                "tag": tag,
                "message": message,
            }
            log_info.update(data)
            
            if log_level == 'info': self.logger.info(json.dumps(log_info, cls=NpEncoder))
            elif log_level == 'debug':self.logger.debug(json.dumps(log_info, cls=NpEncoder))
            elif log_level == 'warn': self.logger.warn(json.dumps(log_info, cls=NpEncoder))
            elif log_level == 'error':self.logger.error(json.dumps(log_info, cls=NpEncoder))


    def connect(self):
        """
        Connect to a Postgres database.
        """
        
        if self.conn is None:
            self.mega = Mega()
            ###Connection to domain
            try:
                self.conn = self.mega.login(self.user, self.password)
                self.stat_info = self.conn.get_storage_space()
                self.log('connection to cloud', 'info', "{}connection to cloud {} established: used {} from {}"\
                                                        .format(self.pref_msg,\
                                                                self.domain,\
                                                                bytes2human(self.stat_info['used']),
                                                                bytes2human(self.stat_info['total'])))
                self.dir_size = self.stat_info['total'] - self.stat_info['used']
            except Exception as error:
                self.log('connection to cloud', 'error', f"{self.pref_msg}Connection to cloud {self.domain}: {error}")
                    
    
    def json_extract(self, obj, key) -> list:
        """
        Recursively fetch values from nested JSON.
        """
        
        arr = []

        def extract(obj, arr, key):
            """
            Recursively search for values of key in JSON tree.
            """
            
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, (dict, list)):
                        extract(v, arr, key)
                    elif k == key:
                        arr.append(v)
            elif isinstance(obj, list):
                for item in obj:
                    extract(item, arr, key)
            return arr

        values = extract(obj, arr, key)
        return values
    

    def listdir(self) -> None:
        """
        List of files in directory of cloud
        by filtering dates of creation/uploading
        as result - table/dataframe with listing of path content.
        Please, specify the directory in the cloud by definition self.dir_name
        """

        self.connect()
        del self.dir_id, self.df_files
        gc.collect()
        self.dir_id = None
        self.df_files = pd.DataFrame(columns = ['fname','size', 'fdate'])
        #--------------------------------------------------------------------------------------------------------------------------------
        if self.conn:
            try:
                self.dir_id, _ = self.conn.find(self.dir_name)
            except Exception as error:
                self.log('connection to cloud', 'error', f"{self.pref_msg}Problem with connection to directory {self.dir_name}: {error}")
            
            ###Proccessing start date ####################################################################################################
            if not self.start_fdate: 
                self.start_fdate = datetime(1970, 1, 1)
            elif not isinstance(self.start_fdate, datetime):
                try:
                    self.start_fdate = parse(str(self.start_fdate))
                except:
                    self.start_fdate = datetime(1970, 1, 1)

            ###Proccessing end date ######################################################################################################
            if not self.end_fdate:
                self.end_fdate = datetime.today()
            elif not isinstance(self.end_fdate, datetime):
                try:
                    self.end_fdate = parse(str(self.end_fdate))
                except:
                    self.end_fdate = datetime.today()
            #-------------------------------------------------------------------------------------------------------------------------------
            if self.end_fdate < self.start_fdate: self.end_fdate = datetime.today()
        #--------------------------------------------------------------------------------------------------------------------------------
        if self.dir_id:
            self.stat_info = self.conn.get_files()
            if isinstance(self.stat_info, dict):
                for k,v in self.stat_info.items():
                    try:
                        if self.dir_id in self.json_extract(v, 'p'):
                            if self.start_fdate <= datetime.fromtimestamp(self.json_extract(v, 'ts')[0]) <= self.end_fdate:
                                self.df_files = self.df_files.append({'fname':self.json_extract(v, 'n')[0],\
                                                                      'size':bytes2human(self.json_extract(v, 's')[0]),\
                                                                      'fdate':datetime.fromtimestamp(self.json_extract(v, 'ts')[0])},\
                                                                        ignore_index = True)
                    except:
                        None
        #---------------------------------------------------------------------------------------------------------------------------------
        if not self.df_files.empty:
            self.df_files = self.df_files.sort_values(by = ['fdate']).reset_index(drop = True)
            self.log('listing cloud folder', 'info', f"{self.pref_msg}Defined {self.df_files.shape[0]} items in folder : {self.dir_name}")
        elif self.dir_id and self.df_files.empty:
            self.log('listing cloud folder', 'warn', f"{self.pref_msg}Folder - {self.dir_name} empty or some unexpected error.")


    def mkdir(self, dir_name: str = '') -> bool:
        """
        Creating folder in cloud storage
        """

        if dir_name == '':
            self.log('checking folder name', 'error', f"{self.pref_msg}Please, specify the folder name")
            return False
        #------------------------------------------------------------------------------------------------------------------------------
        self.connect()
        del self.dir_id
        self.dir_id, go_on = None, False
        #--------------------------------------------------------------------------------------------------------------------------------
        if self.conn:
            try:
                self.dir_id, _ = self.conn.find(dir_name)
                if self.dir_id:
                    self.log('directory in cloud', 'warn', f"{self.pref_msg}directory {dir_name} already exist {self.dir_id}")
                    return True
                else:
                    self.log('directory in cloud', 'info', f"{self.pref_msg}directory {dir_name} not exist")
                    go_on = True
            except Exception as error:
                self.log('directory in cloud', 'info', f"{self.pref_msg}directory {dir_name} not exist: {error}")
                go_on = True
            #----------------------------------------------------------------------------------------------------------------------------
            try:
                if go_on:
                    self.stat_info = self.conn.create_folder(dir_name)
                    self.dir_id = self.stat_info[dir_name.split('/')[-1]]
            except Exception as error:
                self.log('making directory in cloud', 'error', f"{self.pref_msg}Problem during making directory {dir_name}: {error}")
                return False
        #--------------------------------------------------------------------------------------------------------------------------------
        if self.dir_id:
            self.log('making directory in cloud', 'info', f"{self.pref_msg}Folder {dir_name} creared successfully")
            return True
        else:
            self.log('making directory in cloud', 'error', f"{self.pref_msg}Folder {dir_name} has not creared")
            return False
        

    def upload_file_to_cloud(self, fpath: str = '') -> bool:
        """
        uploading file to cloud directory
        """
        
        if os.path.isfile(fpath):
            self.connect()
        else:
            self.log('checking file instance', 'error', f"{self.pref_msg}Please, specify the path to file : {fpath}")
            return False
        #------------------------------------------------------------------------------------------------------------------------------
        del self.dir_id
        self.dir_id = None
        #-------------------------------------------------------------------------------------------------------------------------------
        if self.conn:
            try:
                self.dir_id, _ = self.conn.find(self.dir_name)
            except Exception as error:
                self.log('connection to cloud', 'error', f"{self.pref_msg}Problem with connection to directory {self.dir_name}: {error}")
        #-------------------------------------------------------------------------------------------------------------------------------
        if self.dir_id:
            ### Checking file size and comparing with storage#############################################################################
            sfile_before = os.path.getsize(fpath)
            if self.dir_size < sfile_before:
                self.log('storage size checking', 'error',\
                         f"{self.pref_msg}There are necessary additional space for this file: {bytes2human(self.dir_size)} against {bytes2human(sfile_before)}")
                return False
            else:
                ### uploading file to storage ############################################################################################
                try:
                    self.stat_info = self.conn.upload(fpath, self.dir_id)
                    sfile_after = self.json_extract(self.stat_info, 's')[0]
                    if sfile_before == sfile_after: 
                        self.log("file uploading", 'info', f"{self.pref_msg}Success with uploading {fpath.split('/')[-1]}, size: {bytes2human(sfile_after)}")
                        return True
                    else:
                        self.log("file uploading", 'warn', \
                                f"{self.pref_msg}Difference in size after uploading {fpath.split('/')[-1]}, befor size: {bytes2human(sfile_before)}, after size: {bytes2human(sfile_after)}")
                        return True
                except Exception as error:
                    self.log('file uploading', 'error', f"{self.pref_msg}Unexpected error during file ({fpath.split('/')[-1]}) uploading : {error}")
                    return False
        
        return False


    def close(self):

        if self.conn:
            self.conn = None


class DBredis:
    """
    Redis message Broker class.
    """

    def __init__(self, 
                topic: int = 0, 
                host: str = 'localhost', 
                tz: str = 'Europe/Moscow', 
                username: str = '',
                password: str = '', 
                retention_ms: int = 172800, 
                port: int = 6379, 
                headers: dict = {}):

        self.topic = topic
        self.timezone = tz
        self.headers = headers
        self.host = host
        self.retention_period = retention_ms
        self.user = username
        self.password = password
        self.port = port
        self.dc_result = {}
        self.df_result = pd.DataFrame()
        self.pref_msg = ''
        self.log_levels = ["debug", "info", "warn", "error"]
        self.format_dt = '%Y-%m-%d %H:%M:%S'
        self.logger = None
        self.conn = None

    
    def log(self, tag: str = 'redis-service', log_level: str = 'info', message: str = '', data: dict = {}):
        """
        logging with custom format:
        tag - some tag of action
        message - message for logging
        data - some key-value pairs for additional data of logging
        """

        if self.log_levels.index(log_level) >= self.log_levels.index(log_level) and self.logger:
            log_info = {
                "level": log_level,
                "time": datetime.now(timezone.utc).isoformat(),
                "tag": tag,
                "message": message,
            }
            log_info.update(data)
            
            if log_level == 'info': self.logger.info(json.dumps(log_info, cls=NpEncoder))
            elif log_level == 'debug':self.logger.debug(json.dumps(log_info, cls=NpEncoder))
            elif log_level == 'warn': self.logger.warn(json.dumps(log_info, cls=NpEncoder))
            elif log_level == 'error':self.logger.error(json.dumps(log_info, cls=NpEncoder))


    def connect_broker(self):
        """
        Connect to a Kafka broker as Producer.
        """
                
        if self.conn is None and not all([self.user, self.password]):
            try:
                self.conn = redis.StrictRedis(
                                    host=self.host,
                                    port=self.port,
                                    db=self.topic,
                                    decode_responses=True,
                                    charset='utf-8',
                                    password=self.password,
                                    )
                if self.timezone:
                    self.conn.set('timezone', self.timezone)
                if self.headers != {}:
                    for k,v in self.headers.items():
                        _ = self.conn.set(k, self.change_format_to_str(v))
                    
            except Exception as error:
                self.log('connection to broker', 'error', f"{self.pref_msg}Connection to Broker {self.host}: {error}")
        
    
    def change_format_to_str(self, value: object = None) -> object:
        """
        decoding values
        """

        if isinstance(value, bool):
            value = 1 if value else 0
        elif isinstance(value, bytes):
            value = value.decode()
        elif value is None:
            value = '0'
        elif isinstance(value, (list, dict)):
            value = json.dumps(value, cls = NpEncoder)

        return value


    def publish_message(self, key, value) -> bool:
        """
        publishing data to Broker
        """

        load = False
        self.connect_broker()
        if self.conn:
            try:
                load = self.conn.setex(key, self.retention_period, self.change_format_to_str(value))
            except Exception as error:
                self.log('publishing to broker', 'error', f"Publishing message to topic {self.topic}: {error}")
        #-------------------------------------------------------------------------------------------------------
        self.close()

        return load


    def reading_message(self, key, temp_dc = {}) -> dict:
        """
        messages from que for transform to dict
        """

        self.connect_broker()
        if temp_dc == {}:
            self.dc_result = {key:None}
        elif isinstance(temp_dc, dict):
            self.dc_result = temp_dc
            self.dc_result[key] = None
        else:
            self.dc_result = {key:None}
        #------------------------------------------------------------------------------------------------------------
        if self.conn:
            try:
                self.dc_result[key] = self.change_format_to_str(self.conn.get(key))
            except Exception as error:
                self.log('consuming from broker', 'error', f"reading message ({key}) from topic {self.topic}: {error}")
        #-------------------------------------------------------------------------------------------------------------        
        self.close()

        return self.dc_result

    
    def close(self):

        if self.conn:
            self.conn.close()
            self.conn = None

####################################################################################################
#### engine of execution
####################################################################################################

class AppEngine:

    def __init__(self,
                authorized: bool = False, 
                queue_free: bool = False,
                queue_start: bool = False,
                int_token: str = None, 
                set_cookie: bool = False,
                uncorrect: bool = False,
                logger: object = None,
                request: object = None,
                redisdb: object = None):

        self.authorized = authorized
        self.queue_free = queue_free
        self.queue_start = queue_start
        self.int_token = int_token
        self.token_name_task = 'task_id'
        self.token_task = ''
        self.set_cookie = set_cookie
        self.uncorrect = uncorrect
        self.log_levels = ["debug", "info", "warn", "error"]
        self.response = None
        self.key = ''
        self.delcook = False
        self.parse_post = False
        self.request = request
        self.logger = logger
        self.redisdb = redisdb
        self.token_name = ''

    
    def log(self, tag: str = 'app', log_level: str = 'info', message: str = '', data: dict = {}):
        """
        logging with custom format:
        tag - some tag of action
        message - message for logging
        data - some key-value pairs for additional data of logging
        """

        if self.log_levels.index(log_level) >= self.log_levels.index(log_level) and self.logger:
            log_info = {
                "level": log_level,
                "time": datetime.now(timezone.utc).isoformat(),
                "tag": tag,
                "message": message,
            }
            log_info.update(data)
            
            if log_level == 'info': self.logger.info(json.dumps(log_info, cls=NpEncoder))
            elif log_level == 'debug':self.logger.debug(json.dumps(log_info, cls=NpEncoder))
            elif log_level == 'warn': self.logger.warn(json.dumps(log_info, cls=NpEncoder))
            elif log_level == 'error':self.logger.error(json.dumps(log_info, cls=NpEncoder))


    def auth_process(self, token_name: str = 'token', token: str = '', main_page: bool = True):
        """
        authentification process
        """

        self.token_name = token_name
        try:
            self.int_token = self.request.cookies.get(self.token_name)
            #self.log('parsing cookie', 'info', f"Parsing cookie 'token': {self.int_token}")
            if self.int_token is not None: 
                self.authorized = True
        except Exception as err:
            self.log('parsing cookie', 'error', f"Parsing cookie '{self.token_name}': {err}")
        
        #  Parsing first visit with access token - init internal token -----
        try:
            if not self.authorized and main_page:
                if self.request.args.get(self.token_name) == token:
                    self.int_token = make_guid(datetime.now(), random.randint(*[0,10]))
                    self.set_cookie, self.authorized = True, True
        except Exception as err:
            self.log('parsing GET', 'error', f"Parsing input: {err}")
        
        # if authorized - checking queue busy or free -----------------------
        self.key = f"{self.int_token}_youtube_download"


    def check_status(self):

        try:
            msg = self.redisdb.reading_message(self.key)
            self.queue_free = True if str(msg[self.key]) in ['None','free','0'] else False
            self.log('parsing redis', 'info', f"Parsing redis '{self.key}': {msg}")
        except Exception as err:
            self.log('checking redis', 'error', f"Parsing redis: {err}")
    

    def check_repeat_process(self, token_name: str = 'task_id', token: str = ''):
        """
        authentification process
        """

        self.token_task = None
        try:
            self.token_task = self.request.cookies.get(self.token_name_task)
        except Exception as err:
            self.log('parsing cookie', 'error', f"Parsing cookie '{self.token_name_task}': {err}")
        
        if self.token_task is None:
            self.parse_post = True
        elif self.token_task == token:
            self.parse_post = False
            self.log('parsing cookie', 'info', "The task can not be repeated")
        elif self.token_task != token:
            self.token_task = token
        

    def create_response(self, page_template: str = 'index.html', title: str = 'Youtube Downloader'):

        
        if self.delcook:
            self.authorized = False
        #----------------------------------------------------------------------
        self.response = make_response(
                            render_template(
                                page_template, 
                                title = title,
                                uncorrect = self.uncorrect, 
                                queue_free = self.queue_free, 
                                queue_start = self.queue_start, 
                                authorized = self.authorized,
                            ))
        #----------------------------------------------------------------------
        if self.authorized and self.set_cookie:
            self.response.set_cookie(self.token_name, self.int_token)
        elif self.delcook:
            self.response.set_cookie(self.token_name, expires=0)
        elif self.authorized:
            self.response.set_cookie(self.token_name_task, self.token_task)

    
    def parse_post_params(self, cloud_path: str = 'temp'):
        """
        Parsing POST variables from request
        """

        self.params_task = {
            'fpath':'',
            'key':self.key,
            'links':[],
            'translit':True,
            'bitrate':'96',
            'kind':'',
        }
        #-----------------------------------------------
        try:
            ### parsing path in cloud storage ----------
            self.params_task['fpath'] = self.request.form['path']
            self.params_task['fpath'] = cloud_path if self.params_task['fpath'] == '' else self.params_task['fpath']
            
            ### parsing the source of parsing audio ----
            self.params_task['kind'] = self.request.form['source']
            
            ### parsing bitrate ------------------------
            self.params_task['bitrate'] = self.request.form['bitrate']

            ### parsing translit : do or not -----------
            if 'translit' in self.request.form.keys():
                self.params_task['translit'] = self.request.form['translit']
                self.params_task['translit'] = True if self.params_task['translit'] == 'on' else False
            
            ### parsing general params - del cookies ---
            if 'delcook' in self.request.form.keys():
                self.delcook = self.request.form['delcook']
                self.delcook = True if self.delcook == 'on' else False
            else:
                self.delcook = False
            
            ### parsing links for downloading ----------
            self.params_task['links'] = [self.request.form[f'link_{i}'] for i in range(1,10) if f'link_{i}' in self.request.form.keys()]
            self.params_task['links'] = [x for x in self.params_task['links'] if x != '' and x.startswith('http')]
            if self.params_task['links'] == []: self.uncorrect = True
            
            #-------------------------------------------
            self.parse_post = True
        except Exception as err:
            self.log('parsing POST params', 'error', f"Parsing POST: {err}")
    
####################################################################################################
#### additional procedures 
#####################################################################################################

def make_guid(*args) -> str:
    """
    procedure of making GUID from values in args
    """
    
    return str(uuid.uuid5(uuid.NAMESPACE_OID, '-'.join(map(str, args))))


def translit(s: str = '', rev: bool = False) -> str:
    """ Make translit the words in both ways (from cyrillic to english)"""
    
    ### dicts for transliting from cyrilic to english words #######################################################################
    upper_case_letters = {
        u'А': u'A', u'Б': u'B', u'В': u'V', u'Г': u'G', u'Д': u'D', u'Е': u'E', u'Ё': u'E', u'Ж': u'Zh', u'З': u'Z',
        u'И': u'I', u'Й': u'Y', u'К': u'K', u'Л': u'L', u'М': u'M', u'Н': u'N', u'О': u'O', u'П': u'P', u'Р': u'R',
        u'С': u'S', u'Т': u'T', u'У': u'U', u'Ф': u'F', u'Х': u'H', u'Ц': u'Ts', u'Ч': u'Ch', u'Ш': u'Sh', u'Щ': u'Sch',
        u'Ъ': u'', u'Ы': u'Y', u'Ь': u'', u'Э': u'E', u'Ю': u'Yu', u'Я': u'Ya',
    }
    #-------------------------------------------------------------------------------------------------------------------------------
    lower_case_letters = {
        u'а': u'a', u'б': u'b', u'в': u'v', u'г': u'g', u'д': u'd', u'е': u'e','ё':u'yo', u'ё': u'yo', u'ж': u'zh', u'з': u'z',
        u'и': u'i', u'й': u'y', u'к': u'k', u'л': u'l', u'м': u'm', u'н': u'n', u'о': u'o', u'п': u'p', u'р': u'r',
        u'с': u's', u'т': u't', u'у': u'u', u'ф': u'f', u'х': u'h', u'ц': u'ts', u'ч': u'ch', u'ш': u'sh', u'щ': u'sch',
        u'ъ': u'', u'ы': u'y', u'ь': u'', u'э': u'e', u'ю': u'yu', u'я': u'ya',
    }    
    ### dicts for transliting from english to cyrilic words #######################################################################
    rev_upper_case_letters = {
        'A': 'А','B': 'Б', 'V': 'В', 'G': 'Г', 'D': 'Д', 'E': 'Э', 'Z': 'З', 'I': 'И', 'Y': 'Ы', 'K': 'К','L': 'Л',
        'M': 'М', 'N': 'Н', 'O': 'О', 'P': 'П', 'R': 'Р', 'S': 'С', 'T': 'Т', 'U': 'У', 'F': 'Ф', 'H': 'Х','J':'Дж',
    }
    #-------------------------------------------------------------------------------------------------------------------------------
    rev_lower_case_letters = {
        'a': 'а', 'b': 'б', 'v': 'в', 'g': 'г', 'd': 'д', 'e': 'э', 'z': 'з', 'i': 'и', 'y': 'ы', 'k': 'к','l': 'л',
        'm': 'м', 'n': 'н', 'o': 'о', 'p': 'п', 'r': 'р', 's': 'с', 't': 'т', 'u': 'у', 'f': 'ф', 'h': 'х','j':'дж',
    }
    #-------------------------------------------------------------------------------------------------------------------------------
    pairs = {
        'Zh': 'Ж','Ts': 'Ц','Ch': 'Ч','Sh': 'Ш', 'Sch': 'Щ', 'Yu': 'Ю', 'Ya': 'Я','Yo': 'Ё','yo': 'ё', 'zh': 'ж','ts': 'ц',
        'ch': 'ч', 'sh': 'ш', 'sch': 'щ', 'yu': 'ю', 'ya': 'я','a ':'','A ':'','An ':'','an ':'','The ':'','the ':'', 'of ':'',
        'Of ':'','To ':'к ','to ':'к ','On ':'на ','on ':'на ','in ':'в','In ':'в ','is ':'','Is ':'','are ':'','Are ':'',
    }
    ################################################################################################################################
    
    translit_string = ""
    #------------------------------------------------------------------------------------------------------------------------------
    if not rev:
        for index, char in enumerate(s):
            if char in lower_case_letters.keys():
                char = lower_case_letters[char]
            elif char in upper_case_letters.keys():
                char = upper_case_letters[char]
                if len(s) > index+1:
                    if s[index+1] not in lower_case_letters.keys():
                        char = char.upper()
                else:
                    char = char.upper()
            #---------------------------------------------------
            translit_string += char
    #--------------------------------------------------------------------------------------------------------------------------------
    else:
        for i in pairs.keys():
            if i in string:
                s = s.replace(i, pairs[i])
        #--------------------------------------------------------
        for index, char in enumerate(s):
            if char in rev_lower_case_letters.keys():
                char = rev_lower_case_letters[char]
            elif char in rev_upper_case_letters.keys():
                char = rev_upper_case_letters[char]
                if len(s) > index+1:
                    if s[index+1] not in rev_lower_case_letters.keys():
                        char = char.upper()
                else:
                    char = char.upper()
            #------------------------------------------------------
            translit_string += char
    #--------------------------------------------------------------------------------------------------------------------------------
    
    return translit_string


def clean_string(s: str = '') -> str:

    return re.sub('[!@#«$»]', '', re.sub('[&]', 'and', s))


def hascyrillic(s: str = '') -> bool:
    """
    Checking of existance cyrillic words
    """

    return bool(re.search('[\u0400-\u04FF]', str(s)))


def haseng(s: str = '') -> bool:
    """
    Checking the existing the latin words in text
    """
    
    lower = set('qwertyuiopasdfghjklzxcvbnm')
    
    return lower.intersection(s.lower()) != set()


def strip_non_english(s: str = '') -> str:
    """
    filtering other letters not from english
    """
    
    en_list = re.findall(u'[^\u4E00-\u9FA5]', s)
    
    return ''.join(['' if c not in en_list else c for c in s])