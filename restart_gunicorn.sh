#!/bin/bash

. /home/iwehrman/fit_env/bin/activate

kill `cat gunicorn.pid` 
sleep 3s
python manage.py run_gunicorn 127.0.0.1:1337 --access-logfile=/home/iwehrman/fit/access.log --error-logfile=/home/iwehrman/fit/error.log --pid=/home/iwehrman/fit/gunicorn.pid -D
