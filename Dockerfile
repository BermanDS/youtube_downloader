FROM python:3.8
WORKDIR /usr/app

# install supervisord
RUN apt-get update && apt-get install -y supervisor
RUN apt-get install -y redis-server
RUN apt-get install -y ffmpeg
# copy requirements and install (so that changes to files do not mean rebuild cannot be cached)

## pyrthon env
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip
COPY requirements.txt /usr/app
RUN pip install -r requirements.txt

# copy all files into the container
COPY . /usr/app

# expose port 80 of the container (HTTP port, change to 443 for HTTPS)
#EXPOSE 5009 5555

# needs to be set else Celery gives an error (because docker runs commands inside container as root)
ENV C_FORCE_ROOT=1

# run supervisord
CMD ["/usr/bin/supervisord"]