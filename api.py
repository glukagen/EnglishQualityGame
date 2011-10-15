
import logging
import os
from urlparse import urlparse
from google.appengine.ext import blobstore
from google.appengine.ext.blobstore import *
from google.appengine.ext.webapp import blobstore_handlers
from google.appengine.ext import db
from google.appengine.ext.db import *
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext.webapp import template
from google.appengine.api import *
from google.appengine.api.images import *
from django.utils import simplejson as json
from models import *
from myutil import *
from myjson import *
from google.appengine.api import images
from google.appengine.api import taskqueue


api_list = {}
def registerAPI(name):
    def temp(func):
        if name.startswith("_"):
            api_list["/_api/" + name] = func
        else:
            api_list["/api/" + name] = func
        return func
    return temp


class Meta(webapp.RequestHandler):
    def get(self):
        self.go()
    def post(self):
        self.go()
    def go(self):
        func = api_list[self.request.path]
        func(self)


def getCurrentUser(self):
    user = users.get_current_user()
    if not user:
        raise BaseException("must be logged in")
    username = user.nickname()
    if self.request.get("me"):
        if users.is_current_user_admin():
            username = self.request.get("me")
        elif username != self.request.get("me"):
            raise BaseException("must be admin to set user")
    return getUser(username)
    

# /api/enterContest
@registerAPI("enterContest")
def api_enterContest(self):
    u = getCurrentUser(self)
    e = enterContest(u)
    
    self.response.headers['Content-Type'] = 'text/html'
    self.response.out.write(json.dumps(e))


# /api/submitResult
@registerAPI("submitResult")
def api_submitResult(self):
    u = getCurrentUser(self)
    e = Entry.get(Key(self.request.get("entry")))
    text = self.request.get("text")
    ok = submitResult(u, e, text)
    
    self.response.headers['Content-Type'] = 'text/html'
    self.response.out.write(json.dumps({"ok" : ok}))


# /api/saveVotes
@registerAPI("saveVotes")
def api_saveVotes(self):
    ok = submitResult(
            getCurrentUser(self), 
            Entry.get(Key(self.request.get("entry"))),
            self.request.get("english"),
            self.request.get("creative")
    )
    
    self.response.headers['Content-Type'] = 'text/html'
    self.response.out.write(json.dumps({"ok" : ok}))


# /api/getUserInfo
@registerAPI("getUserInfo")
def api_getContests(self):
    me = getCurrentUser(self)
    user = me
    if self.request.get("user"):
        user = User.get(Key(self.request.get("user")))
    ret = getUserInfo(me, user, 10)
    
    self.response.headers['Content-Type'] = 'text/html'
    self.response.out.write(json.dumps(ret))


# /api/getEntriesJSON
@registerAPI("getEntriesJSON")
def api_getEntriesJSON(self):
    def getUserJso(u):
        return {
            "key" : str(u.key()),
            "username" : u.username,
            "eloScore" : u.eloScore,
            "creativeScore": u.creativeScore,
        }
    entries = []
    for i in Entry.all():
        entries.append({
            "key" : str(i.key()),
            "user" : getUserJso(i.user),
            "contest" : str(i.contest.key()),
            "time" : i.time,
            "deadline" : i.deadline,
            "mytype" : i.mytype,
            "flip" : i.mytype,
            "text" : i.text,
            'creativeText': i.creativeText,
        })
        
    self.response.out.write(json.dumps(entries))
 

# /api/getContestsJSON
@registerAPI("getContestsJSON")
def api_getContestsJSON(self):
    contests = []
    for i in Contest.all():
        contests.append({
            "key" : str(i.key()),
            "text" : i.text,
            "textMin" :i.textMin,
            "textMax" : i.textMax,
            "time" : i.time,
            "complete" : i.complete,
            "entry1": str(i.entry1.key()) if i.entry1 else "",
            "entry2": str(i.entry2.key()) if i.entry2 else "",
            "vote1": str(i.vote1.key()) if i.vote1 else "",
            "vote2": str(i.vote2.key()) if i.vote2 else "",
            "vote3": str(i.vote3.key()) if i.vote3 else "",
            "winner": str(i.winner.key()) if i.winner else "",
            "creativeWinner": str(i.creativeWinner.key()) if i.creativeWinner else "",
        })
        
    self.response.out.write(json.dumps(contests))    


# /_api/_clear
@registerAPI("_clear")
def api_clear(self):
    clearModels()
    
    self.response.headers['Content-Type'] = 'text/html'
    self.response.out.write(json.dumps({"ok!" : True}))


# /_api/_eval
@registerAPI("_eval")
def api_eval(self):
    buf = []
    def output(a):
        buf.append(a)
    exec self.request.get("cmd") in globals(), locals()
    
    ret = json.dumps({"ok!" : True})
    if len(buf) > 0:
        ret = "\n".join(buf)
    
    self.response.headers['Content-Type'] = 'text/html'
    self.response.out.write(ret)


# /_api/_getContests
@registerAPI("_getContests")
def func(self):
    self.response.headers['Content-Type'] = 'text/html'
    self.response.out.write(json.dumps(getAllContests()))


# /_api/_clear
@registerAPI("_clear")
def func(self):
    for i in User.all():
        i.delete()
    for i in Entry.all():
        i.delete()
    for i in Contest.all():
        i.delete()
    
    self.response.headers['Content-Type'] = 'text/html'
    self.response.out.write(json.dumps({"ok!" : True}))


# /_api/_temp
@registerAPI("_temp")
def api_eval(self):
    for u in User.all():
        u.username = u.userid
        u.put()
    
    self.response.headers['Content-Type'] = 'text/html'
    self.response.out.write(json.dumps({"ok!" : True}))


application = webapp.WSGIApplication([
    ('/api/.*', Meta),
    ('/_api/.*', Meta),
], debug = True)


def main():
    run_wsgi_app(application)


if __name__ == "__main__":
    main()

