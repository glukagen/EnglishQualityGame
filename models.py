
import logging
import os
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
from google.appengine.api import taskqueue
import random
from django.utils import simplejson as json
import hashlib
from myutil import *
from wordlist import *


class User(db.Model):
    username = db.StringProperty()
    eloScore = db.FloatProperty(default=1500.0)
    creativeScore = db.FloatProperty(default=1500.0)
    numEntries = db.IntegerProperty(default=0)
    numVotes = db.IntegerProperty(default=0)


class Entry(db.Model):
    user = db.ReferenceProperty(User, collection_name="user")
    contest = db.ReferenceProperty()
    time = db.IntegerProperty()
    deadline = db.IntegerProperty()
    mytype = db.StringProperty()
    flip = db.BooleanProperty()
    text = db.TextProperty()
    creativeText = db.TextProperty()


class Contest(db.Model):
    text = db.TextProperty()
    textMin = db.IntegerProperty()
    textMax = db.IntegerProperty()
    time = db.IntegerProperty()
    complete = db.BooleanProperty(default=False)
    creativeComplete = db.BooleanProperty(default=False)
    
    entry1 = db.ReferenceProperty(Entry, collection_name="entry1")
    entry2 = db.ReferenceProperty(Entry, collection_name="entry2")
    
    vote1 = db.ReferenceProperty(Entry, collection_name="vote1")
    vote2 = db.ReferenceProperty(Entry, collection_name="vote2")
    vote3 = db.ReferenceProperty(Entry, collection_name="vote3")
    
    winner = db.ReferenceProperty(Entry, collection_name="winner")    
    creativeWinner = db.ReferenceProperty(Entry, collection_name="creativeWinner")
    
    
##########

def clearModels():
    for a in User.all():
        a.delete()
    for a in Entry.all():
        a.delete()
    for a in Contest.all():
        a.delete()


def getUser(username):
    u = User.gql("where username = :username", username=username).get()
    if not u:
        u = User(username = username)
        u.put()
    return u


def getAllContests():
    def getUserJso(u):
        return {
            "key" : str(u.key()),
            "username" : u.username,
            "eloScore" : u.eloScore,
            "creativeScore": u.creativeScore,
        }
            
    def getEntryJso(e):
        return {
            "user" : getUserJso(e.user),
            "mytype" : e.mytype,
            "text" : e.text,
            "creativeText": e.creativeText,
        } if e else None
        
    def getContestJso(c):
        return {
            "text" : c.text,
            "complete" : c.complete, 
            "creativeComplete": c.creativeComplete,
            "entry1": getEntryJso(c.entry1),
            "entry2": getEntryJso(c.entry2),
            "vote1": getEntryJso(c.vote1),
            "vote2": getEntryJso(c.vote2),
            "vote3": getEntryJso(c.vote3),
        }
        
    return [getContestJso(c) for c in Contest.all()]


def getUserInfo(me, target, count):
    def isMe(u):
        return me.key() == u.key()
        
    targetIsMe = isMe(target)
        
    def getUserJso(u):
        if isMe(u):
            return {
                "key": str(me.key()),
                "username": me.username,
                "eloScore": me.eloScore,
                "creativeScore": me.creativeScore,
            }
        else:
            return {
                "key" : str(u.key()),
                "username" : u.username[0:4] + "..",
                "eloScore" : u.eloScore,
                "creativeScore": u.creativeScore,
            }
            
    def getEntryJso(e):
        return {
            "user" : getUserJso(e.user),
            "mytype" : e.mytype,
            "text" : e.text,
            "creativeText": e.creativeText,
        } if e else None
        
    def getContestJso(c):
        if not c.complete and not targetIsMe:
            return
        jso = {
            "text" : c.text,
            "complete" : c.complete,
            "creativeComplete": c.creativeComplete,
        }
        if c.complete:
            jso["entry1"] = getEntryJso(c.entry1)
            jso["entry2"] = getEntryJso(c.entry2)
            jso["vote1"] = getEntryJso(c.vote1)
            jso["vote2"] = getEntryJso(c.vote2)
            jso["vote3"] = getEntryJso(c.vote3)
        return jso
        
    data = {
        "me" : getUserJso(me),
        "user" : getUserJso(target),
        "highScores" : [getUserJso(u) for u in User.gql("order by eloScore desc limit 10")]
    }
    
    data["contests"] = []
    for e in Entry.gql("where user = :user order by time desc", user=target):
        jso = getContestJso(e.contest)
        if jso:
            data["contests"].append(jso)
        if len(data["contests"]) >= count:
            break
    
    return data    


def processContest(cKey):
    c = Contest.get(cKey)
    now = mytime()

    def run(creative):
        
        def choose(value, creativeValue):
            return creativeValue if creative else value  
    
        def updateScores(winnerEntry, loserEntry, p):
            winner = winnerEntry.user
            loser = loserEntry.user
            
            def lock(cKey):
                c = Contest.get(cKey)
                if not choose(c.complete, c.creativeComplete):
                    if creative:
                        c.creativeComplete = True
                    else:
                        c.complete = True    
                    if p > 0:
                        if creative:
                            c.creativeWinner = winnerEntry
                        else:
                            c.winner = winnerEntry    
                    c.put()
                    return True
            
            if db.run_in_transaction(lock, c.key()):
                wDelta, lDelta = eloDeltas(
                        choose(winner.eloScore, winner.creativeScore),
                        choose(loser.eloScore, loser.creativeScore), 
                        p)
                def func(uKey, delta):
                    u = User.get(uKey)
                    if creative:
                        u.creativeScore += delta
                    else:
                        u.eloScore += delta
                    u.put()
                db.run_in_transaction(func, winner.key(), wDelta)
                db.run_in_transaction(func, loser.key(), lDelta)
            
        if not choose(c.complete, c.creativeComplete):
            if (c.entry1 and (c.entry1.text or now > c.entry1.deadline)) \
                and (c.entry2 and (c.entry2.text or now > c.entry2.deadline)):
                # both entries are done, or have timed out
                if c.entry1.text and c.entry2.text:
                    # both entries are done, so check votes
                    if (c.vote1 and (choose(c.vote1.text, c.vote1.creativeText) \
                                     or now > c.vote1.deadline)) \
                        and (c.vote2 and (choose(c.vote2.text, c.vote2.creativeText) \
                                          or now > c.vote2.deadline)) \
                        and (c.vote3 and (choose(c.vote3.text, c.vote3.creativeText) \
                                           or now > c.vote3.deadline)):
                        # votes are done, or have timed out, so process votes
                        votes = {"1" : 0, "2" : 0}
                        for text in (choose(c.vote1.text, c.vote1.creativeText),
                            choose(c.vote2.text, c.vote2.creativeText),
                            choose(c.vote3.text, c.vote3.creativeText),):
                            if text:
                                votes[text] += 1
                        if votes["1"] > votes["2"]:
                            updateScores(c.entry1, c.entry2, float(votes["1"]) / 3)
                        elif votes["2"] > votes["1"]:
                            updateScores(c.entry2, c.entry1, float(votes["2"]) / 3)
                        else:
                            updateScores(c.entry1, c.entry2, 0)
                else:
                    # an entry timed out, so no need to vote
                    if c.entry1.text:
                        updateScores(c.entry1, c.entry2, 1.0 / 3)
                    elif c.entry2.text:
                        updateScores(c.entry2, c.entry1, 1.0 / 3)
                    else:
                        updateScores(c.entry1, c.entry2, 0)     
    
    run(False)
    run(True)


def enterContest(user):
    now = mytime()
    
    def returnJso(e, c):
        jso = {
            "key" : str(e.key()),
            "contest" : {
                "text" : c.text,
                "textMin" : c.textMin,
                "textMax" : c.textMax
            },
            "deadline" : e.deadline,
            "mytype" : e.mytype
        }
        if e.mytype == "vote":
            entries = [c.entry1.text, c.entry2.text] if not e.flip else [c.entry2.text, c.entry1.text]
            jso["contest"]["entry1"] = {
                "text" : entries[0]
            }
            jso["contest"]["entry2"] = {
                "text" : entries[1]
            }
        return jso

    # see if this person is already doing a contest
    e = Entry.gql("where user = :user order by time desc", user=user).get()
    if e and not e.text and now < e.deadline:
        return returnJso(e, e.contest)
    
    # make sure that people don't write or vote too much,
    # we want to maintain a 2/3 ratio of writings to votings
    x = min(user.numEntries // 2, user.numVotes // 3)
    allowedEntry = user.numEntries - (x * 2) < 3
    allowedVote = user.numVotes - (x * 3) < 5
    
    def enter(c):
        e = Entry()
        e.user = user
        e.contest = c
        e.time = now
        e.flip = random.random() > 0.5
        
        prop = None
        if not c.entry1:
            if allowedEntry:
                prop = "entry1"
                e.deadline = e.time + (5 * 60 * 1000)
                e.mytype = "entry"
        elif not c.entry2:
            if allowedEntry:
                prop = "entry2"
                e.deadline = e.time + (5 * 60 * 1000)
                e.mytype = "entry"
        else:
            if c.entry1.text and c.entry2.text:
                if allowedVote:
                    if not c.vote1:
                        prop = "vote1"
                        e.deadline = e.time + (1 * 60 * 1000)
                        e.mytype = "vote"
                    elif not c.vote2:
                        prop = "vote2"
                        e.deadline = e.time + (1 * 60 * 1000)
                        e.mytype = "vote"
                    elif not c.vote3:
                        prop = "vote3"
                        e.deadline = e.time + (1 * 60 * 1000)
                        e.mytype = "vote"
        if not prop:
            return
        e.put()
        def func(cKey):
            c = Contest.get(cKey)
            if not eval("c." + prop):
                ee = e
                exec("c." + prop + " = ee") in globals(), locals()
                c.put()
                return True
        if db.run_in_transaction(func, c.key()):
            
            # keep track of how many times we do the different kinds
            # of activities (writing and voting)
            def func(uKey):
                u = User.get(uKey)
                if e.mytype == "entry":
                    u.numEntries += 1
                else:
                    u.numVotes += 1
                u.put()
            db.run_in_transaction(func, user.key())
            
            taskqueue.add(url='/_api/_eval', params={'cmd': 'processContest("' + str(c.key()) + '")'}, eta=datetime.datetime.fromtimestamp((e.deadline + 1000) / 1000.0))
            return returnJso(e, c)
        else:
            e.delete()

    for c in Contest.gql("where complete = False order by time"):
        if not Entry.gql("where contest = :c and user = :user", c=c, user=user).get():
            jso = enter(c)
            if jso:
                return jso
        
    # none found, so make a new one
    if allowedEntry:
        c = Contest()
        c.text = " ".join(getWords(3))
        c.textMin = 2
        c.textMax = 200
        c.time = now
        c.put()
        return enter(c)


def submitResult(u, e, text, creativeText=None):
    print "Text: %s" % text
    print "creativeText: %s" % creativeText
    
    def flip(_text):
        return "1" if _text == "2" else "2"
    
    def check(_text):
        if not re.match("1|2", _text):
            raise BaseException("invalid vote")
        
    if u.key() != e.user.key():
        raise BaseException("this is not your entry")
        
    if e.mytype == "vote":
        if e.flip:
            text = flip(text)
            if creativeText:
                creativeText = flip(creativeText)
    
    now = mytime()
    c = e.contest
    
    if e.mytype == "vote":
        check(text)
        if creativeText:
            check(creativeText)
    else:
        mylen = len(text)
        if mylen < c.textMin or mylen > c.textMax:
            raise BaseException("invalid text, must be within %d and %d characteres" % (c.textMin, c.textMax))
        words = c.text.split(" ")
        for word in words:
            if not re.search("(?i)" + word, text):
                raise BaseException("invalid text, must contain the word \"" + word + "\"")
    
    def func(eKey):
        e = Entry.get(eKey)
        if now <= e.deadline and not e.text:
            e.text = text
            if creativeText:
                print "set creative text"
                e.creativeText = creativeText
            print e
            e.put()
            return True
    ret = db.run_in_transaction(func, e.key())

    if e.mytype == "vote":
        taskqueue.add(url='/_api/_eval', params={'cmd': 'processContest("' + str(c.key()) + '")'})
    
    return ret

