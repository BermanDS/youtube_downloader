from .utils import *


#####################################################################################################
#### Youtube procedures 
#####################################################################################################

def download_audio(url_list: list = [], path_to_save: str = '',num_trying: int = 2, **params_youtube) -> dict:
    """
    main procedure for parsing audio content from youtube by using library youtube_dl
    """
    
    res_path = {}   ## result dict

    if not isinstance(url_list, list): url_list = [url_list]
    params_youtube['outtmpl'] = os.path.join(path_to_save, '%(title)s.%(ext)s')
    
    #-------------------------------------------------------------------------
    ydl = youtube_dl.YoutubeDL(params_youtube)
    
    for url in url_list:
        res = {}
        for _ in range(num_trying):
            try:
                res = ydl.extract_info(url)
                if res != {}: break
            except:
                sleep(9)
        #---------------------------------------------------------------------
        if res == {} or 'title' not in res.keys(): 
            res_path[url] = None
            continue
        #---------------------------------------------------------------------
        title = res['title'].translate(str.maketrans('', '', string.punctuation)).replace(' ','')
        #---------------------------------------------------------------------
        temp_ls = [x[0] for x in map(lambda x: [x, x.translate(str.maketrans('', '', string.punctuation)).replace(' ','')],\
                                     os.listdir(path_to_save)) if title in x[1]]
        if temp_ls == []:
            res_path[url] = None
        else:
            res_path[url] = os.path.join(path_to_save, temp_ls[0])
        #---------------------------------------------------------------------
    
    return res_path