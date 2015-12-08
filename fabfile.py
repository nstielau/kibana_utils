#!/usr/bin/env python

import re
import datetime
from dateutil import parser
import json
import os
import sys
import time
import socket

import boto
import boto.s3
from boto.s3.key import Key

import requests

from fabric.api import *

ELASTIC_SEARCH_HOST = os.environ.get('ELASTIC_SEARCH_HOST', 'localhost')
ELASTIC_SEARCH_PORT = os.environ.get('ELASTIC_SEARCH_PORT', 9200)

###############
# Helpers

def _get_s3_bucket_vars():
    global BUCKET_NAME, PATH_PREFIX
    BUCKET_NAME = os.environ['KIBANA_BUCKET']
    PATH_PREFIX = os.environ['KIBANA_PREFIX']

def _es_url(path):
    return 'http://{0}:{1}{2}'.format(ELASTIC_SEARCH_HOST, ELASTIC_SEARCH_PORT, path)

def _get_boto_connection():
    return boto.connect_s3()

def _get_backup_key(format=None):
    """Get backup key given the specified format"""
    _get_s3_bucket_vars()
    suffix = _get_time_string(format)
    return '%s/%s-dashboard_backup_%s.json' % (PATH_PREFIX, socket.gethostname(), suffix)

def _get_time_string(format):
    """Return a string of the current date using the given format"""
    return datetime.datetime.today().strftime(format).lower()

def _get_dashboards():
    """Query dashboards stored in ElasticSearch"""
    return requests.get(_es_url('/kibana-int/dashboard/_search?q=*&size=1000')).text

def _get_dashboard(id):
    """Query dashboard by name/id in ElasticSearch"""
    data = json.loads(requests.get(_es_url('/kibana-int/dashboard/{0}'.format(id))).text)
    return data['_source']

def _create_dashboard(id, data):
    """Create a dashboard with the id and data provided"""
    if isinstance(data, dict):
        data = json.dumps(data)
    r = requests.put(_es_url('/kibana-int/dashboard/{0}'.format(id)), data)
    if r.status_code in [requests.codes.ok, 201]:
        return True
    else:
        raise Exception("Failed, status: {0}. Body: {1}".format(r.status_code, r.text))

def _convert_dashboard_v0_v1(data_str):
    """Convert a kibana dashboard using logstash event-v0 style keys to v1

    NOTE: this converter is naive. It takes a json string and simply regexes on
          common patterns.
    """
    data_str = re.sub("@fields.", "", data_str)
    data_str = re.sub(r"@((?!timestamp)[a-zA-Z\d\-_]+)", r"\1", data_str)
    return data_str

def _get_backup_object(key):
    """Get boto object from key"""
    _get_s3_bucket_vars()
    conn = _get_boto_connection()
    bucket = conn.get_bucket(BUCKET_NAME)
    for item in bucket.list():
        if key == item.key:
            return item
    return None

def _get_backup_objects():
    _get_s3_bucket_vars()
    conn = _get_boto_connection()
    bucket = conn.get_bucket(BUCKET_NAME)
    return bucket.list()

def _do_backup(backup_formats=None):
    """Backups up dashboards from Elastic Search"""
    if not backup_formats:
        raise ValueError("You must supply backup path formats")

    _get_s3_bucket_vars()
    conn = _get_boto_connection()
    bucket = conn.get_bucket(BUCKET_NAME)

    dashboard_dump = _get_dashboards()

    backup_paths = []
    for backup_format in backup_formats:
        backup_paths.append(_get_backup_key(backup_format))

    for key_path in backup_paths:
        print 'Uploading backup to Amazon S3 bucket %s/%s' % (BUCKET_NAME, key_path)
        # Update the dashboard backup
        k = Key(bucket)
        k.key = key_path
        k.set_contents_from_string(dashboard_dump)


###############
# Tasks

@task
def verify_backups():
    """A sensu compatible verification of backup"""
    for item in _get_backup_objects():
        if _get_backup_key('today') == item.key:
            contents = item.get_contents_as_string()
            created_at = parser.parse(item.last_modified)
            created_ago = int(time.time()) - int(created_at.strftime("%s"))
            if len(contents) == 0:
                print "Backup is empty"
                sys.exit(1)
            elif created_ago > 60*60*24*2:
                print "No recent backup found (last upload is {0} seconds old)".format(created_ago)
                sys.exit(1)
            else:
              print "Backup is recent and non-empty"
              sys.exit(0)
    print "No backups found"
    sys.exit(1)

@task
def delete_dashboards():
    """Delete dashboards from elastic search"""
    dashboards = json.loads(_get_dashboards())['hits']['hits']
    for dashboard in dashboards:
        print "Deleting  {0}".format(dashboard["_id"])
        r = requests.delete(_es_url('/kibana-int/dashboard/{0}'.format(dashboard["_id"])))
        if r.status_code != requests.codes.ok:
            print "Error: {0}".format(response)

@task
def restore_dashboards(backup_key):
    """Restores dashboards from given s3 key"""
    backup_object = _get_backup_object(backup_key)
    if backup_object:
        dashboards = json.loads(backup_object.get_contents_as_string())['hits']['hits']
        for dashboard in dashboards:
            dash_id = dashboard["_id"]
            data = dashboard['_source']
            print "Restoring dashboard {0}".format(dash_id)
            response = requests.post(_es_url('/kibana-int/dashboard/{0}'.format(dash_id)), json.dumps(data))
            if response.status_code != requests.codes.ok:
                print "Error: {0}".format(response)
    else:
        print "Could not find backup '{0}'".format(backup_key)

@task
def export_dashboard(name, filename):
    """Get dashboard by name from ElasticSearch. args: name (required), filename (required)"""
    with open(filename, 'w') as f:
        f.write(json.dumps(_get_dashboard(name)))
    print "Dashboard exported to: {0}".format(filename)

@task
def import_dashboard(name, filename):
    """import a dashboard from json file. args: name (required), filename (required)"""
    with open(filename) as f:
        data = json.load(f)
    if _create_dashboard(name, data) == True:
        print "Success."
    else:
        print "FAILED."

@task
def convert_dashboard_v0_v1(orig_filename, new_filename):
    """convert an exported kibana dashboard using logstash event-v0 fields to event-v1 fields. args: orig_filename (required), new_filename (required)"""
    orig_contents = ''
    with open(orig_filename, 'r') as orig_fd:
        orig_contents = orig_fd.read()
    with open(new_filename, 'w') as new_fd:
        new_fd.write(_convert_dashboard_v0_v1(orig_contents))

@task
def list_dashboards():
    """Lists the dashboard from ElasticSearch"""
    dashboards = json.loads(_get_dashboards())['hits']['hits']
    print "Dashboards:"
    for dashboard in dashboards:
        print "  {0}".format(dashboard["_id"])

@task(default=True)
def list_backups():
    """Lists backups on S3"""
    _get_s3_bucket_vars()
    for item in _get_backup_objects():
        if PATH_PREFIX in item.key and not item.key.endswith('/'):
            size = len(item.get_contents_as_string())
            print "Kibana dashboard backup: {0} ({1} characters)".format(item.key, size)

@task
def print_backup(key):
    """Shows contents of a backup on S3"""
    print _get_backup_object(key).get_contents_as_string()

@task
def backup(*backup_formats):
    """Backups up dashboards from Elastic Search.
    Takes path formats as args, and will interpolate python date strings.
    i.e.
    `fab backup:%A,today` will yield a backup file HOSTNAME-DAYOFWEEK.json and HOSTNAME-today.json
    or you can get fancy:
    `fab backup:"%Y-%m-%d__%H-%M"`
    by default, it will store one backup per day for a week, one backup per month for a year.
    """
    default_backup_formats = ["%A", "%B", "today"]
    _do_backup(backup_formats or default_backup_formats)

if __name__ == '__main__':
   backup()
