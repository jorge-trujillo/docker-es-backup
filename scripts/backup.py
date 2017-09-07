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

# Settings
MAX_RETRIES = 10
SCROLL_TIME = '1m'
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

def get_doc_count(url, index):

    response = requests.get("{}/{}/_count".format(url, index))
    if response.status_code != 200:
        print "Error getting count from {}, response code was {}".format(url, response.status_code)
        exit(1)

    count_data = json.loads(response.content)
    return count_data['count']


def get_indices(url):
    response = requests.get("{}/_cat/indices".format(url))
    if response.status_code != 200:
        print "Error getting indices from {}, response code was {}".format(url, response.status_code)
        exit(1)

    index_lines = response.content.split('\n')

    indices = {}
    for line in index_lines:
        sections = re.split('\s+', line)
        if len(sections) >= 3:
            index_name = sections[2]
            # Get the count
            doc_count = get_doc_count(url, index_name)
            indices[index_name] = doc_count

    return indices


def query_es(url, query=None, scroll_id=None):
    """Query elasticsearch with the provided query. Retry if needed"""
    attempt = 1

    if scroll_id is None:
        query_data = query
    else:
        query_data = scroll_id

    while attempt < MAX_RETRIES:
        try:
            r = requests.post(url, data=query_data)
            if r.status_code == 200:
                content = json.loads(r.content)
                return content

        except:
            print "Attempt {}/{}: Error getting data from {}".format(attempt, MAX_RETRIES, url)

        attempt += 1
        time.sleep(1)

    print 'Fatal error trying to get data, all attempts exhausted'
    exit(1)


def write_to_disk(file_path, data):
    """Write all data to the file path, creating folders if needed"""
    # If dir doesn't exist, create it
    folder_path = os.path.dirname(file_path)
    if len(folder_path) > 0 and not os.path.exists(folder_path):
        os.makedirs(folder_path)

    # Write the data
    data_file = open(file_path, 'w')
    data_file.write(data)
    data_file.close()


def backup_index(url, index):

    # Make the directories we need
    print ' - Checking write permission to current directory'
    try:
        os.makedirs("{}/data".format(index))
    except:
        print ' - Unable to write to the current directory, please resolve this and try again'
        exit(1)

    # Download and save the settings
    print " - Downloading '{}' settings".format(index)

    r = requests.get("{}/{}/_settings".format(url, index))
    if r.status_code != 200:
        print " - Unable to get settings for index '{}', error code: {}".format(index, r.status_code)
        exit(1)

    write_to_disk("{}/settings.json".format(index), r.content)

    # Download and save the schema
    print " - Downloading '{}' schema".format(index)

    r = requests.get("{}/{}/_mapping".format(url, index))
    if r.status_code != 200:
        print " - Unable to get schema for index '{}', error code: {}".format(index, r.status_code)
        exit(1)

    write_to_disk("{}/schema.json".format(index), r.content)

    # Download the data
    query = {
        "query": {
            "indices": {
                "indices": [index],
                "query": {
                    "match_all": {}
                }
            }
        },
        "sort": ["_doc"]
    }
    query = json.dumps(query)

    # Initial query
    data = query_es("{}/{}/_search?scroll={}&size=1000".format(url, index, SCROLL_TIME), query=query)
    write_to_disk("{}/data/{}".format(index, 'initial'), json.dumps(data['hits']['hits']))

    scroll_id = data['_scroll_id']
    total_hits = data['hits']['total']
    progress = len(data['hits']['hits'])

    time_start = time.time()
    last_log = time.time()
    finished = False
    count = 0

    while not finished:

        count += 1
        content = query_es("{}/_search/scroll?scroll={}".format(url, SCROLL_TIME), scroll_id=scroll_id)
        scroll_id = content['_scroll_id']
        number = len(content['hits']['hits'])

        # Do progress calculation
        progress += number
        percent_complete = (progress / float(total_hits)) * 100
        elapsed_time = time.time() - time_start
        processing_rate = progress / float(elapsed_time)
        remaining_time = (total_hits - progress) / processing_rate

        if remaining_time > 3600:
            remaining_time_string = "{:0.1f} hours".format(remaining_time / 3600)
        else:
            remaining_time_string = "{:0.1f} minutes".format(remaining_time / 60)

        if time.time() - last_log > 10 or number < 1:
            last_log = time.time()
            print " - {} pass {}: Got {} results".format(index, count, number)
            print "   -> {}/{} documents complete ({:0.1f}%)".format(progress, total_hits, percent_complete)
            print "   -> Processing rate is {:0.0f} docs/second, {} remaining".format(processing_rate,
                                                                                    remaining_time_string)

        if number < 1:
            finished = True
        else:
            write_to_disk("{}/data/{}/{}".format(index, count % 20, count), json.dumps(content['hits']['hits']))

    # Write a count to the index folder
    write_to_disk("{}.COUNT".format(index), str(progress))

    # Zip up the data
    filename = "{}.{}".format(index, INDEX_FILE_EXTENSION)
    tar = tarfile.open(filename, "w:gz")
    tar.add(index)
    tar.close()

    # Delete the directory
    shutil.rmtree(index)
    print " - Complete. Index file is: {}".format(filename)


# ----------------------------------------------

# Read command line args
parser = argparse.ArgumentParser(description='Elasticsearch server backup - v1.0.0')

# Required
parser.add_argument('--host', help='Path for elasticsearch server (i.e. http://server:9200', required=True)
parser.add_argument('--index', help='Index to back up', required=False)
parser.add_argument('--output', help='Directory to put backup in', required=True)

args = parser.parse_args()

index = args.index
url = args.host

# Change to output path
os.chdir(args.output)

# Verify server
print "Using ElasticSearch at {}, backing up to {}".format(url, args.output)
if not verify_server(url):
    exit(1)

# Check with the user
if not index:
    server_path = os.path.join(args.output, 'server_backup')
    print "Backing up *server* '{}' to {}".format(url, server_path)
    print 'Ctrl+C now to abort...'
    time.sleep(3)

    # Back up templates

    print 'Downloading templates'

    r = requests.get("{}/_template".format(url, index))
    if r.status_code != 200:
        print "Unable to get schema for index '{}', error code: {}".format(index, r.status_code)
        exit(1)

    write_to_disk("{}/templates.json".format(server_path), r.content)

    # Back up all indices
    try:
        if not os.path.exists(server_path):
            os.mkdir(server_path)
    except:
        print 'Unable to write to the current directory, please resolve this and try again'
        exit(1)

    # List of workers
    worker_list = []

    # Change directory into the server path
    os.chdir(server_path)

    # Get all indices
    all_indices = get_indices(url)
    for index, count in all_indices.iteritems():
        print "* Checking index {} with {} docs --------------".format(index, count)

        process_index = False
        count_file = "{}.COUNT".format(index)
        if not os.path.exists(count_file):
            print " - Could not find an existing count file in {}".format(count_file)
            process_index = True
        else:
            with open(count_file) as f:
                saved_count = f.read().rstrip()

                if int(saved_count) != count:
                    print " - Old count {} differs from current count {}!".format(saved_count, count)
                    process_index = True

        if process_index and count > 0:
            print " - Going forward with backup for {}".format(index)
            if os.path.exists("{}.{}".format(index, INDEX_FILE_EXTENSION)):
                os.remove("{}.{}".format(index, INDEX_FILE_EXTENSION))

            # Get a free worker
            free_worker(worker_list)
            # backup_index(url, index)
            p = multiprocessing.Process(target=backup_index, args=(url, index))
            worker_list.append(p)
            p.start()

        else:
            print " - Index {} is up to date!".format(index)

else:  # Only backup one index
    if index is None:
        print 'You must provide an index to use this mode.'
        exit(1)

    print "Backing up *index* '{}'".format(index)
    print 'Ctrl+C now to abort...'
    time.sleep(3)

    # Back-up the index
    backup_index(url, index)

exit(0)
