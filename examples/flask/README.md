# Flask
The basic blog app built with Flask + pyseed.

## Install
Clone the lastest version.
```shell script
# clone
git clone https://github.com/okosioc/pyseed
cd pyseed/examples/flask
```
Create a virtualenv and activate it:
```shell script
python3 -m venv venv
. venv/bin/activate
```
Install requirements:
```shell script
pip install -r requirements.txt
# install pyseed from source code
pip install -e ../..
```

## Run
```shell script
python3 manage.py runserver
```
Open http://127.0.0.1:6060 in a browser.