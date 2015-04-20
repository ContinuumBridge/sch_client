#!/usr/bin/env python
# sch_client.py
# Copyright (C) ContinuumBridge Limited, 2015 - All Rights Reserved
# Unauthorized copying of this file, via any medium is strictly prohibited
# Proprietary and confidential
# Written by Peter Claydon
#
"""
Bit of a botch for now. Just stick actions from incoming requests into threads.
"""

import json
import requests
import websocket
import time
import signal
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.MIMEImage import MIMEImage
import subprocess
import logging
import logging.handlers
import twilio
import twilio.rest
from twisted.internet import threads
from twisted.internet import reactor, defer
from subprocess import call

config = {}
# Production
HOME                  = "/home/ubuntu/"
CB_ADDRESS            = "portal.continuumbridge.com"
KEY                   = "df2a0c10/QLjOvOvIk4qD8Pe9eo4daJl+5CM1RvtNXDk5lfzPMHA62ChfJse7cDo"
DBURL                 = "http://onepointtwentyone-horsebrokedown-1.c.influxdb.com:8086/"
CB_LOGGING_LEVEL      = "INFO"
CB_LOGFILE            = HOME + "sch_client/sch_client.log"
TWILIO_ACCOUNT_SID    = "AC72bb42908df845e8a1996fee487215d8" 
TWILIO_AUTH_TOKEN     = "717534e8d9e704573e65df65f6f08d54"
TWILIO_PHONE_NUMBER   = "+441183241580"
CONFIG_READ_INTERVAL  = 600
 
logger = logging.getLogger('Logger')
logger.setLevel(CB_LOGGING_LEVEL)
handler = logging.handlers.RotatingFileHandler(CB_LOGFILE, maxBytes=10000000, backupCount=5)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

def nicetime(timeStamp):
    localtime = time.localtime(timeStamp)
    milliseconds = '%03d' % int((timeStamp - int(timeStamp)) * 1000)
    now = time.strftime('%H:%M:%S, %d-%m-%Y', localtime)
    return now

def sendMail(bid, sensors, to, timeStamp, intruder=False):
    user = config["user"]
    password = config["password"]
    # Create message container - the correct MIME type is multipart/alternative.
    msg = MIMEMultipart('alternative')
    if intruder:
        msg['Subject'] = "Intruder Alert for " + bid + " at " + nicetime(timeStamp)
    else:
        msg['Subject'] = "Night Wandering Alert for " + bid + " at " + nicetime(timeStamp)
    msg['From'] = config["from"]
    recipients = to.split(',')
    [p.strip(' ') for p in recipients]
    if len(recipients) == 1:
        msg['To'] = to
    else:
        msg['To'] = ", ".join(recipients)
    # Create the body of the message (a plain-text and an HTML version).
    text = "Activity detected from sensors: " + sensors + " at " + nicetime(timeStamp) + " \n"
    htmlText = text
    # Record the MIME types of both parts - text/plain and text/html.
    part1 = MIMEText(text, 'plain')
    part2 = MIMEText(htmlText, 'html')
    msg.attach(part1)
    msg.attach(part2)
    mail = smtplib.SMTP('smtp.gmail.com', 587)
    mail.ehlo()
    mail.starttls()
    mail.login(user, password)
    mail.sendmail(user, recipients, msg.as_string())
    logger.debug("Sent mail")
    mail.quit()
       
def postData(dat, bid):
    url = ""
    for b in config["bridges"]:
        if b["bid"] == bid:
            if "database" in b:
                url = DBURL + "db/" + b["database"] + "/series?u=root&p=27ff25609da60f2d"
            else:
                url = DBURL + "db/Bridges/series?u=root&p=27ff25609da60f2d"
            break
    headers = {'Content-Type': 'application/json'}
    status = 0
    logger.debug("url: %s", url)
    r = requests.post(url, data=json.dumps(dat), headers=headers)
    status = r.status_code
    if status !=200:
        logger.warning("POSTing failed, status: %s", status)

def sendSMS(bid, sensors, to, intruder=False):
    numbers = to.split(",")
    for n in numbers:
       try:
           client = twilio.rest.TwilioRestClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
           if intruder:
               messageBody =  "Intruder alert for " + bid + ", detected by " + sensors
           else:
               messageBody =  "Night wandering alert for " + bid + ", detected by " + sensors
           message = client.messages.create(
               body = messageBody,
               to = n,
               from_ = TWILIO_PHONE_NUMBER
           )
           sid = message.sid
           logger.debug("Sent sms for bridge %s to %s", bid, str(n))
       except Exception as ex:
           logger.warning("sendSMS, unable to send message. BID: %s, number: %s", bid, str(n))
           logger.warning("%s Exception: %s %s", ModuleName, type(ex), str(ex.args))

class Connection(object):
    def __init__(self):
        signal.signal(signal.SIGINT, self.signalHandler)  # For catching SIGINT
        signal.signal(signal.SIGTERM, self.signalHandler)  # For catching SIGTERM
        #logger.basicConfig(filename=CB_LOGFILE,level=CB_LOGGING_LEVEL,format='%(asctime)s %(levelname)s: %(message)s')
        self.readConfig()
        self.lastActive = {}
        self.reconnects = 0
        self.reauthorise = 0
        logger.info(json.dumps(config, indent=4))
        reactor.callLater(CONFIG_READ_INTERVAL, self.readConfigLoop)
        reactor.callLater(0.5, self.authorise)
        reactor.run()

    def signalHandler(self, signal, frame):
        logger.debug("%s signalHandler received signal", ModuleName)
        reactor.stop()

    def readConfig(self):
        global config
        call(HOME + "sch_client/sch_git.sh", shell=True)
        print "git called"
        configFile = HOME + "sch_client/sch_client.config"
        try:
            with open(configFile, 'r') as f:
                newConfig = json.load(f)
                logger.info( "Read sch_app.config")
                config.update(newConfig)
                logger.info("Config read")
                print "config file read"
        except Exception as ex:
            logger.warning("sch_app.config does not exist or file is corrupt")
            logger.warning("Exception: %s %s", str(type(ex)), str(ex.args))
        for c in config:
            if c.lower in ("true", "t", "1"):
                config[c] = True
            elif c.lower in ("false", "f", "0"):
                config[c] = False

    def readConfigLoop(self):
        self.readConfig()
        reactor.callLater(CONFIG_READ_INTERVAL, self.readConfigLoop)

    def authorise(self):
        try:
            self.reconnects = 0
            auth_url = "http://" + CB_ADDRESS + "/api/client/v1/client_auth/login/"
            auth_data = '{"key": "' + KEY + '"}'
            auth_headers = {'content-type': 'application/json'}
            response = requests.post(auth_url, data=auth_data, headers=auth_headers)
            self.cbid = json.loads(response.text)['cbid']
            self.sessionID = response.cookies['sessionid']
            self.ws_url = "ws://" + CB_ADDRESS + ":7522/"
            reactor.callLater(0.1, self.connect)
        except Exception as ex:
            logger.warning("sch_app. Unable to authorise with server")
            logger.warning("Exception: %s %s", str(type(ex)), str(ex.args))

    def connect(self):
        try:
            websocket.enableTrace(True)
            self.ws = websocket.WebSocketApp(
                            self.ws_url,
                            on_open   = self.onopen,
                            on_error = self.onerror,
                            on_close = self.onclose,
                            header = ['sessionID: {0}'.format(self.sessionID)],
                            on_message = self.onmessage)
            self.ws.run_forever()
        except Exception as ex:
            self.reconnects += 1
            logger.warning("Websocket connection failed")
            logger.warning("Exception: %s %s", type(ex), str(ex.args))

    def onopen(self, ws):
        self.reconnects = 0
        logger.debug("on_open")

    def onclose(self, ws):
        if self.reconnects < 4:
            logger.debug("on_close. Attempting to reconnect.")
            reactor.callLater((self.reconnects+1)*5, self.connect)
        else:
            logger.error("Max number of reconnect tries exceeded. Reauthenticating.")
            reactor.callLater(5, self.authorise)

    def onerror(self, ws, error):
        logger.error("Error: %s", str(error))

    def onmessage(self, ws, message):
        try:
            msg = json.loads(message)
            logger.info("Message received: %s", json.dumps(msg, indent=4))
        except Exception as ex:
            logger.warning("sch_app. onmessage. Unable to load json")
            logger.warning("Exception: %s %s", str(type(ex)), str(ex.args))
        if msg["body"] == "connected":
            logger.info("Connected to ContinuumBridge")
        elif msg["body"]["m"] == "alarm":
            bid = msg["source"].split("/")[0]
            found = False
            for b in config["bridges"]:
                if b["bid"] == bid:
                    self.lastActive[bid] = msg["body"]["t"]
                    bridge = b["friendly_name"]
                    if "email" in b:
                        email = b["email"]
                        reactor.callInThread(sendMail, bridge, msg["body"]["s"], b["email"], msg["body"]["t"])
                    if "sms" in b:
                        reactor.callInThread(sendSMS, bridge, msg["body"]["s"], b["sms"])
                    found = True
                    break
            if found:
                ack = {
                        "source": config["cid"],
                        "destination": msg["source"],
                        "body": {
                                    "n": msg["body"]["n"]
                                }
                      }
                self.ws.send(json.dumps(ack))
            else:
                logger.warning("Message from unknown bridge: %s", bid)
        elif msg["body"]["m"] == "intruder":
            bid = msg["source"].split("/")[0]
            found = False
            for b in config["bridges"]:
                if b["bid"] == bid:
                    self.lastActive[bid] = msg["body"]["t"]
                    bridge = b["friendly_name"]
                    if "email" in b:
                        email = b["email"]
                        reactor.callInThread(sendMail, bridge, msg["body"]["s"], b["email"], msg["body"]["t"], True)
                    if "sms" in b:
                        reactor.callInThread(sendSMS, bridge, msg["body"]["s"], b["sms"], True)
                    found = True
                    break
            if found:
                ack = {
                        "source": config["cid"],
                        "destination": msg["source"],
                        "body": {
                                    "n": msg["body"]["n"]
                                }
                      }
                self.ws.send(json.dumps(ack))
            else:
                logger.warning("Message from unknown bridge: %s", bid)
        elif msg["body"]["m"] == "data":
            logger.info("Data messsage received")
            bid = msg["source"].split("/")[0]
            dat = msg["body"]["d"]
            for d in dat:
                d["columns"] = ["time", "value"]
            dd = dat
            logger.debug("Posting to InfluxDB: %s", json.dumps(dd, indent=4))
            reactor.callInThread(postData, dd, bid)
            ack = {
                    "source": config["cid"],
                    "destination": msg["source"],
                    "body": {
                                "n": msg["body"]["n"]
                            }
                  }
            self.ws.send(json.dumps(ack))

if __name__ == '__main__':
    connection = Connection()
