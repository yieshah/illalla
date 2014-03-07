﻿#! /usr/bin/python2
# vim: set fileencoding=utf-8
"""Retrieve checkins tweets"""
from timeit import default_timer as clock
import TwitterAPI as twitter
from api_keys import TWITTER_CONSUMER_KEY as consumer_key
from api_keys import TWITTER_CONSUMER_SECRET as consumer_secret
from api_keys import TWITTER_ACCESS_TOKEN as access_token
from api_keys import TWITTER_ACCESS_SECRET as access_secret
import CommonMongo as cm
DB = cm.connect_to_db('foursquare')[0]
import read_foursquare as rf
import CheckinCrawler as cc
CRAWLER = cc.CheckinCrawler()
CITIES_TREE = rf.obtain_tree()
from Queue import Queue
from threading import Thread
from utils import get_nested
import cities
import locale
locale.setlocale(locale.LC_ALL, 'C')  # to parse date
UTC_DATE = '%a %b %d %X +0000 %Y'
FullCheckIn = rf.namedtuple('FullCheckIn', ['id', 'lid', 'uid', 'city', 'loc',
                                            'time', 'tid', 'tuid', 'msg'])
CHECKINS_QUEUE = Queue(4*cc.vc.POOL_SIZE)
GETTING_MORE_TWEETS = True
NUM_VALID = 0


def parse_tweet(tweet):
    """Return a CheckIn from `tweet` or None if it is not located in a valid
    city"""
    loc = get_nested(tweet, 'coordinates')
    city = None
    if not loc:
        # In that case, we would have to follow the link to know whether the
        # checkin falls within our cities but that's too costly so we drop it
        # (and introduce a bias toward open sharing users I guess)
        return None
    lon, lat = loc['coordinates']
    city = rf.find_town(lat, lon, CITIES_TREE)
    if not (city and city in cities.SHORT_KEY):
        return None
    tid = get_nested(tweet, 'id_str')
    urls = get_nested(tweet, ['entities', 'urls'], [])
    # short url of the checkin that need to be expand, either using bitly API
    # or by VenueIdCrawler. Once we get the full URL, we still need to request
    # 4SQ (500 per hours) to get info (or look at page body, which contains the
    # full checkin in a javascript field)
    lid = [url['expanded_url'] for url in urls
           if '4sq.com' in url['expanded_url']][0]
    uid = get_nested(tweet, ['user', 'id_str'])
    msg = get_nested(tweet, 'text')
    try:
        time = rf.datetime.strptime(tweet['created_at'], UTC_DATE)
        time = cities.utc_to_local(city, time)
    except ValueError:
        print('time: {}'.format(tweet['created_at']))
        return None
    return FullCheckIn('', lid, '', city, loc, time, tid, uid, msg)


def post_process(checkins):
    """use `crawler` to follow URL within `checkins` and update them with
    information regarding the actual Foursquare checkin."""
    infos = CRAWLER.checkins_from_url([c.lid for c in checkins])
    to_insert = []
    for checkin, info in zip(checkins, infos):
        if info:
            converted = checkin._asdict()
            id_, uid, vid, time = info
            del converted['id']
            converted['_id'] = id_
            converted['uid'] = uid
            converted['lid'] = vid
            converted['time'] = time
            to_insert.append(converted)
    return to_insert


def insert_checkins():
    """batch insert checkins into DB."""
    waiting_for_crawling = []
    while GETTING_MORE_TWEETS:
        checkin = CHECKINS_QUEUE.get()
        assert checkin
        waiting_for_crawling.append(checkin)
        if len(waiting_for_crawling) == CRAWLER.pool_size:
            perform_insertion(post_process(waiting_for_crawling))
            del waiting_for_crawling[:]
    perform_insertion(post_process(waiting_for_crawling))


def perform_insertion(complete):
    """Insert `complete` checkins into the DB."""
    try:
        DB.checkin.insert(complete, continue_on_error=True)
        print('insert {}'.format(len(complete)))
        for _ in complete:
            CHECKINS_QUEUE.task_done()
    except cm.pymongo.errors.DuplicateKeyError:
        pass
    except cm.pymongo.errors.OperationFailure as err:
        print(err, err.code)

if __name__ == '__main__':
    #pylint: disable=C0103
    api = twitter.TwitterAPI(consumer_key, consumer_secret,
                             access_token, access_secret)
    req = api.request('statuses/filter', {'track': '4sq com'})
    nb_tweets = 0
    valid_checkins = []
    t = Thread(target=insert_checkins, name='InsertCheckins')
    t.daemon = True
    t.start()
    start = clock()
    end = start + 9*60*90
    for item in req.get_iterator():
        candidate = parse_tweet(item)
        nb_tweets += 1
        if candidate:
            CHECKINS_QUEUE.put_nowait(candidate)
            NUM_VALID += 1
            if clock() >= end:
                GETTING_MORE_TWEETS = False
                break
    CHECKINS_QUEUE.join()
    report = 'insert {} valid checkins in {:.2f}s (out of {}).'
    print(report.format(NUM_VALID, clock() - start, nb_tweets))