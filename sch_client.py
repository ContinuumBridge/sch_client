#!/usr/bin/env python
# sch_client.py
# Copyright (C) ContinuumBridge Limited, 2015 - All Rights Reserved
# Unauthorized copying of this file, via any medium is strictly prohibited
# Proprietary and confidential
# Written by Peter Claydon
#
import httplib 
import json
import requests
import websocket
import time
import signal
from twisted.internet import threads
from twisted.internet import defer
from twisted.internet import reactor
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.MIMEImage import MIMEImage

config = {}
# Production
CB_ADDRESS          = "portal.continuumbridge.com"
KEY                 = "df2a0c10/QLjOvOvIk4qD8Pe9eo4daJl+5CM1RvtNXDk5lfzPMHA62ChfJse7cDo"
START_DELAY         = 60
SWITCH_INTERVAL     = 60
DESTINATION         = "BID27/AID10"

def sendMail(bid, sensor, to):
    user = config["user"]
    password = config["password"]
    # Create message container - the correct MIME type is multipart/alternative.
    msg = MIMEMultipart('alternative')
    msg['Subject'] = "Night Wandering Alert for " + bid
    msg['From'] = config["from"]
    recipients = to.split(',')
    [p.strip(' ') for p in recipients]
    if len(recipients) == 1:
        msg['To'] = to
    else:
        msg['To'] = ", ".join(recipients)
    # Create the body of the message (a plain-text and an HTML version).
    text = "Activity detected from sensor: " + sensor + " \n"
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
    print "Sent mail"
    mail.quit()
       
    def signalHandler(self, signal, frame):
        logging.debug("%s signalHandler received signal", ModuleName)
        reactor.stop()
        exit()

class Connection(object):
    def __init__(self):
        self.boilerState = 0
        self.readConfig()
        self.lastActive = {}
        print(json.dumps(config, indent=4))
        reactor.callInThread(self.connect)
        reactor.run()

    def readConfig(self):
        global config
        configFile = "sch_client.config"
        try:
            with open(configFile, 'r') as f:
                newConfig = json.load(f)
                print "Read sch_app.config"
                config.update(newConfig)
        except Exception as ex:
            print "sch_app.config does not exist or file is corrupt"
            print "Exception: " + str(type(ex)) + str(ex.args)
        for c in config:
            if c.lower in ("true", "t", "1"):
                config[c] = True
            elif c.lower in ("false", "f", "0"):
                config[c] = False
        reactor.callLater(30, self.readConfig)

    def connect(self) :
        auth_url = "http://" + CB_ADDRESS + "/api/client/v1/client_auth/login/"
        auth_data = '{"key": "' + KEY + '"}'
        auth_headers = {'content-type': 'application/json'}
        response = requests.post(auth_url, data=auth_data, headers=auth_headers)
        self.cbid = json.loads(response.text)['cbid']
        sessionID = response.cookies['sessionid']

        ws_url = "ws://" + CB_ADDRESS + ":7522/"
        websocket.enableTrace(True)
        self.ws = websocket.WebSocketApp(
                        ws_url,
                        on_open   = self._onopen,
                        header = ['sessionID: {0}'.format(sessionID)],
                        on_message = self._onmessage)
        self.ws.run_forever()

    def _onopen(self, ws):
        print "on_open"

    def _onmessage(self, ws, message):
        msg = json.loads(message)
        print "Message received:"
        print(json.dumps(msg, indent=4))
        if msg["body"] == "connected":
            print "Connected to ContinuumBridge"
        elif msg["body"]["m"] == "alarm":
            bid = msg["source"].split("/")[0]
            found = False
            for b in config["bridges"]:
                if b["bid"] == bid:
                    #print("Found: ", json.dumps(b, indent=4))
                    if bid not in self.lastActive:
                        self.lastActive[bid] = 0
                    if msg["body"]["t"] - self.lastActive[bid] > 60:
                        self.lastActive[bid] = msg["body"]["t"]
                        bridge = b["friendly_name"]
                        email = b["email"]
                        found = True
                        break
                    else:
                        print "More activity within time window for ", bid
            if found:
                sendMail(bridge, msg["body"]["s"], email)

            ack = {
                    "source": config["cid"],
                    "destination": msg["source"],
                    "body": {
                                "n": msg["body"]["n"]
                            }
                  }
            #print "Sending: "
            #print(json.dumps(ack, indent=4))
            self.ws.send(json.dumps(ack))
            #print "Message sent"
    
if __name__ == '__main__':
    connection = Connection()
