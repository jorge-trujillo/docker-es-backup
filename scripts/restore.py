#!/usr/bin/env python

# Dependencies
import os
import time
import json
import tarfile
import shutil
import argparse

import re
import requests
import multiprocessing

INDEX_FILE_EXTENSION = 'esbackup.gz'

max_workers = 4

# Get a free worker process. Will block if there are none available
def free_worker(worker_list):
    while 1:
        if len(worker_list) < max_workers:
            return True

        for worker in worker_list:
            if not worker.is_alive():
                worker_list.remove(worker)
                print "* Worker is free"
                return True

        # Sleep for 2 seconds
        time.sleep(2)

def get_doc_count(url, index):

    response = requests.get("{}/{}/_count".format(url, index))
    if response.status_code != 200:
        print "Error getting count from {}, response code was {}".format(url, response.status_code)
        return 0

    count_data = json.loads(response.content)
    return count_data['count']


def verify_server(url):
    """Check the server at the given url, and return true if the server is accessible"""

    try:
        response = requests.get(url)
        if response.status_code != 200:
            print "Error hitting ElasticSearch on {}, response code was {}".format(url, response.status_code)
        else:
            print 'Verified ElasticSearch server'
            return True
    except:
        print "Unable to hit ElasticSearch on {}".format(url)

    return False


def override_replicas(url, index, replicas):
    try:
        req = {
            "index": {
                "number_of_replicas": replicas
            }
        }
        print " - Updating replicas to {} for index {}".format(replicas, index)
        r = requests.post("{}/{}/_settings".format(url, index), data=req)
    except:
        print "Unable to hit ElasticSearch on {}".format(url)


def delete_index(url, index):
    try:
        delete_path = "{}/{}".format(url, index)
        response = requests.delete(delete_path)
        if response.status_code == 200:
            print " - Index {} was deleted".format(index)
            return True
        else:
            print " - Error deleting index at path {}, response code was {}".format(delete_path, response.status_code)
    except:
        print " - Unable to hit ElasticSearch on {}".format(url)

    return False

def process_file(url, index, subdir, index_file):
    # Read in data file
    data_file = open(os.path.join(subdir, index_file))
    items = json.loads(data_file.read())
    data_file.close()

    bulk = ''
    item_count = 0

    for item_index, item in enumerate(items):
        # Remove sort field
        item.pop('sort', None)
        source = item["_source"]
        del item["_source"]
        command = {"index": item}
        bulk = bulk + json.dumps(command) + "\n" + json.dumps(source) + "\n"
        item_count += 1

        if item_count >= max_items or item_index >= len(items) - 1:
            print " - Putting {} items from {} - {}".format(item_count, index, index_file)
            r = requests.post("{}/_bulk".format(url), data=bulk)
            if r.status_code != 200:
                print " - Could not submit {} to {}".format(data_file, url)
                print " - Error was {}: {}".format(r.status_code, r.content)

            bulk = ""
            item_count = 0

def count_from_saved_file(count_file):
    count = 0
    if os.path.exists(count_file):
        with open(count_file) as f:
            saved_count = f.read().rstrip()
            count = int(saved_count)
    return count

def restore_index(url, index, force=False, replicas=None, max_items=1000):
    # Check the index doesnt already exist
    r = requests.get("{}/{}/_mapping".format(url, index))
    if r.status_code != 404:
        if not force:
            print " - The index {} already exists. Please ensure it does not exist first as it will be skipped.".format(
                index)
            print " - This command can be executed to do this: curl -XDELETE {}/{}".format(url, index)
            return
        else:
            if not delete_index(url, index):
                exit(1)

    # Unzip the backup file
    filename = "{}.esbackup.gz".format(index)
    tar = tarfile.open(filename)
    tar.extractall()
    tar.close()

    # Read the settings
    settings_file = open("{}/settings.json".format(index), "r")
    settings = json.loads(settings_file.read())
    settings_file.close()

    main_index = settings.keys()[0]
    settings = settings[main_index]
    if 'settings' in settings:
        settings = settings["settings"]

    # Remove unsupported settings
    for setting_name in ['creation_date', 'provided_name', 'uuid', 'version']:
        settings['index'].pop(setting_name, None)

    # Read the schema
    schema_file = open("{}/schema.json".format(index), "r")
    schema = json.loads(schema_file.read())
    schema_file.close()

    schema = schema[main_index]
    if 'mappings' in schema:
        schema = schema['mappings']

    # Create the index on the server
    data = {
        "mappings": schema,
        "settings": settings
    }
    r = requests.put("{}/{}".format(url, main_index), data=json.dumps(data))
    if r.status_code != 200:
        print " - Unable to put the index to the server {}, aborting".format(url)
        print " - {}: {}".format(r.status_code, r.content)
        exit(1)

    if replicas:
        override_replicas(url, index, replicas)

    # List of workers
    worker_list = []

    # Load up the data files and put them all in
    for subdir, dirs, files in os.walk("{}/data".format(index)):
        for index_file in files:

            # Get a free worker
            free_worker(worker_list)
            p = multiprocessing.Process(target=process_file, args=(url, index, subdir, index_file))
            worker_list.append(p)
            p.start()

        # Create index alias if needed
        if main_index != index:
            alias = {
                "actions": [
                    {
                        "add": {"index": main_index, "alias": index}
                    }
                ]
            }

            r = requests.post("{}/_aliases".format(url), data=json.dumps(alias))
            if r.status_code != 200:
                print " - Unable to create the alias of the index ({}), aborting".format(main_index)
                print r.content
                exit(1)

    # Clean up the directory
    shutil.rmtree(index)

# ----------------------------------------------

# Read command line args
parser = argparse.ArgumentParser(description='Elasticsearch server restore - v1.0.0')

# Required
parser.add_argument('--host', help='Path for elasticsearch server (i.e. http://server:9200', required=True)
parser.add_argument('--index', help='Index to restore', required=False)
parser.add_argument('--force', help='Force restore of indices, even if they exist.',
                    action='store_true', default=False, required=False)
parser.add_argument('--path', help='Path to folder with index data', required=False)
parser.add_argument('--replicas', help='Replicas override', required=False)
parser.add_argument('--max_items', help='Max size of restore batch', required=False, default=1000)

args = parser.parse_args()

index = args.index
url = args.host
force = args.force
replicas = args.replicas

max_items = 1000
if args.max_items:
    max_items = int(args.max_items)

# Get the elasticsearch server
print "Using ElasticSearch at {}".format(url)
if not verify_server(url):
    exit(1)

# Check with the user
if not args.index:
    print "Restoring server from '{}'".format(args.path)
    print 'Ctrl+C now to abort...'

    os.chdir(args.path)

    # Restore the templates
    templates_file = open("templates.json".format(index), "r")
    templates = json.loads(templates_file.read())
    templates_file.close()

    for template, template_data in templates.iteritems():
        r = requests.put("{}/_template/{}".format(url, template), data=json.dumps(template_data))
        if r.status_code != 200:
            print "Unable to put the template {} to the server {}, aborting".format(template, url)
            print "{}: {}".format(r.status_code, r.content)
            exit(1)

    # Restore the indices
    for file_name in os.listdir('.'):
        if os.path.isfile(file_name) and (INDEX_FILE_EXTENSION in file_name):
            index = file_name.replace(".{}".format(INDEX_FILE_EXTENSION), '')
            if force:
                print "Performing force restoring for index '{}' -------------------- ".format(index)
                restore_index(url, index, force, replicas=args.replicas, max_items=max_items)
            else:
                count_file = "{}.COUNT".format(index)
                backup_doc_count = count_from_saved_file(count_file)
                index_count = get_doc_count(url, index)
                print "* Stats from server for index {} holds {} docs --------------".format(index, index_count)
                print "Doc count from saved file {}".format(backup_doc_count)
                if index_count != backup_doc_count:
                    print "Index count mismatch. Restoring index '{}' -------------------- ".format(index)
                    restore_index(url, index, bool('true'), replicas=args.replicas, max_items=max_items)
                else:
                    print "Index {} skipping as doc count match from backup".format(index)

else:
    print "Restoring index '{}'".format(index)
    print 'Ctrl+C now to abort...'
    time.sleep(3)

    restore_index(url, index, force=args.force, replicas=args.replicas, max_items=max_items)

print "Finished"
