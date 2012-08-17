# -*- coding: utf-8 -*-
#!/usr/bin/env python
#
# Copyright 2012 BigML
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""BigML.io Python bindings.

This is a simple binding to BigML.io, the BigML API.

Example usage (assuming that you have previously set up the BIGML_USERNAME and
BIGML_API_KEY environment variables):

from bigml.api import BigML

api = BigML()
source = api.create_source('./data/iris.csv')
dataset = api.create_dataset(source)
model = api.create_model(dataset)
prediction = api.create_prediction(model, {'sepal width': 1})
api.pprint(prediction)

"""
import logging
FORMAT = '%(asctime)-15s: %(message)s'
logging.basicConfig(format=FORMAT)
LOGGER = logging.getLogger('BigML')

import sys
import time
import os
import re
import pprint
import requests

from threading import Thread

import urllib2
from poster.encode import multipart_encode
from poster.streaminghttp import register_openers
import unidecode

try:
    import simplejson as json
except ImportError:
    import json

from urlparse import urlparse

register_openers()

# Base URL
BIGML_URL = "https://bigml.io/andromeda/"

# Basic resources
SOURCE_PATH = 'source'
DATASET_PATH = 'dataset'
MODEL_PATH = 'model'
PREDICTION_PATH = 'prediction'

# Development Mode URL
BIGML_DEV_URL = "https://bigml.io/dev/andromeda/"

# Check BigML.io host’s SSL certificate
# DO NOT CHANGE IT.
VERIFY = True

# Resource Ids patterns
SOURCE_RE = re.compile(r'^%s/[a-f,0-9]{24}$' % SOURCE_PATH)
DATASET_RE = re.compile(r'^%s/[a-f,0-9]{24}$' % DATASET_PATH)
MODEL_RE = re.compile(r'^%s/[a-f,0-9]{24}$' % MODEL_PATH)
PREDICTION_RE = re.compile(r'^%s/[a-f,0-9]{24}$' % PREDICTION_PATH)

# Headers
SEND_JSON = {'Content-Type': 'application/json;charset=utf-8'}
ACCEPT_JSON = {'Accept': 'application/json;charset=utf-8'}

# HTTP Status Codes from https://bigml.com/developers/status_codes
HTTP_OK = 200
HTTP_CREATED = 201
HTTP_ACCEPTED = 202
HTTP_NO_CONTENT = 204
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_PAYMENT_REQUIRED = 402
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_METHOD_NOT_ALLOWED = 405
HTTP_LENGTH_REQUIRED = 411
HTTP_INTERNAL_SERVER_ERROR = 500

# Resource status codes
WAITING = 0
QUEUED = 1
STARTED = 2
IN_PROGRESS = 3
SUMMARIZED = 4
FINISHED = 5
FAULTY = -1
UNKNOWN = -2
RUNNABLE = -3

# Map status codes to labels
STATUSES = {
    WAITING: "WAITING",
    QUEUED: "QUEUED",
    STARTED: "STARTED",
    IN_PROGRESS: "IN_PROGRESS",
    SUMMARIZED: "SUMMARIZED",
    FINISHED: "FINISHED",
    FAULTY: "FAULTY",
    UNKNOWN: "UNKNOWN",
    RUNNABLE: "RUNNABLE"
}

PROGRESS_BAR_WIDTH = 50

def invert_dictionary(dictionary):
    """Inverts a dictionary.

    Useful to make predictions using fields' names instead of Ids.
    It does not check whether new keys are duplicated though.

    """
    return dict([[value['name'], key]
        for key, value in dictionary.items()])

def slugify(str):
    """Translates a field name into a variable name."""

    str = unidecode.unidecode(str).lower()
    return re.sub(r'\W+', '_', str)

##############################################################################
#
# BigML class
#
##############################################################################


class BigML(object):
    """Entry point to create, retrieve, list, update, and delete
    sources, datasets, models and predictions.

    Full API documentation on the API can be found from BigML at:
        https://bigml.com/developers

    Resources are wrapped in a dictionary that includes:
        code: HTTP status code
        resource: The resource/id
        location: Remote location of the resource
        object: The resource itself
        error: An error code and message

    """
    def __init__(self, username=None, api_key=None, dev_mode=False):
        """Initializes the BigML API.

        If left unspecified, `username` and `api_key` will default to the
        values of the `BIGML_USERNAME` and `BIGML_API_KEY` environment
        variables respectively.

        If `dev_mode` is set to `True`, the API will be used in development
        mode where the size of your datasets are limited but you are not
        charged any credits.

        """
        if username is None:
            username = os.environ['BIGML_USERNAME']
        if api_key is None:
            api_key = os.environ['BIGML_API_KEY']

        self.auth = "?username=%s;api_key=%s;" % (username, api_key)
        self.dev_mode = dev_mode

        if dev_mode:
            self.URL = BIGML_DEV_URL
        else:
            self.URL = BIGML_URL

        # Base Resource URLs
        self.SOURCE_URL = self.URL + SOURCE_PATH
        self.DATASET_URL = self.URL + DATASET_PATH
        self.MODEL_URL = self.URL + MODEL_PATH
        self.PREDICTION_URL = self.URL + PREDICTION_PATH

    def _create(self, url, body):
        """Creates a new remote resource.

        Posts `body` in JSON to `url` to create a new remote resource.

        Returns a BigML resource wrapped in a dictionary that includes:
            code: HTTP status code
            resource: The resource/id
            location: Remote location of the resource
            object: The resource itself
            error: An error code and message

        """
        code = HTTP_INTERNAL_SERVER_ERROR
        resource_id = None
        location = None
        resource = None
        error = {
            "status": {
                "code": code,
                "message": "The resource couldn't be created"}}
        try:
            response = requests.post(url + self.auth, headers=SEND_JSON,
                data=body, verify=VERIFY)

            code = response.status_code

            if code == HTTP_CREATED:
                location = response.headers['location']
                resource = json.loads(response.content, 'utf-8')
                resource_id = resource['resource']
                error = None
            elif code in [
                HTTP_BAD_REQUEST,
                HTTP_UNAUTHORIZED,
                HTTP_PAYMENT_REQUIRED,
                HTTP_NOT_FOUND]:
                error = json.loads(response.content, 'utf-8')
            else:
                LOGGER.error("Unexpected error (%s)" % code)
                code = HTTP_INTERNAL_SERVER_ERROR

        except ValueError:
            LOGGER.error("Malformed response")
        except requests.ConnectionError:
            LOGGER.error("Connection error")
        except requests.Timeout:
            LOGGER.error("Request timed out")
        except requests.RequestException:
            LOGGER.error("Ambiguous exception occurred")

        return {
            'code': code,
            'resource': resource_id,
            'location': location,
            'object': resource,
            'error': error}

    def _get(self, url):
        """Retrieves a remote resource.

        Uses HTTP GET to retrieve a BigML `url`.

        Returns a BigML resource wrapped in a dictionary that includes:
            code: HTTP status code
            resource: The resource/id
            location: Remote location of the resource
            object: The resource itself
            error: An error code and message

        """
        code = HTTP_INTERNAL_SERVER_ERROR
        resource_id = None
        location = url
        resource = None
        error = {
            "status": {
                "code": HTTP_INTERNAL_SERVER_ERROR,
                "message": "The resource couldn't be retrieved"}}

        try:
            response = requests.get(url + self.auth, headers=ACCEPT_JSON,
                verify=VERIFY)
            code = response.status_code

            if code == HTTP_OK:
                resource = json.loads(response.content, 'utf-8')
                resource_id = resource['resource']
                error = None
            elif code in [HTTP_BAD_REQUEST, HTTP_UNAUTHORIZED, HTTP_NOT_FOUND]:
                error = json.loads(response.content, 'utf-8')
            else:
                LOGGER.error("Unexpected error (%s)" % code)
                code = HTTP_INTERNAL_SERVER_ERROR

        except ValueError:
            LOGGER.error("Malformed response")
        except requests.ConnectionError:
            LOGGER.error("Connection error")
        except requests.Timeout:
            LOGGER.error("Request timed out")
        except requests.RequestException:
            LOGGER.error("Ambiguous exception occurred")

        return {
            'code': code,
            'resource': resource_id,
            'location': location,
            'object': resource,
            'error': error}

    def _list(self, url, query_string=''):
        """Lists all existing remote resources.

        Resources in listings can be filterd using `query_string` formatted
        according to the syntax and fields labeled as filterable in the BigML
        documentation for each resource.

        Sufixes:
            __lt: less than
            __lte: less than or equal to
            __gt: greater than
            __gte: greater than or equal to

        For example:

            'size__gt=1024'

        Resources can also be sortened including a sort_by statement within
        the `query_sting`. For example:

            'order_by=size'

        """
        code = HTTP_INTERNAL_SERVER_ERROR
        meta = None
        resources = None
        error = {
            "status": {
                "code": code,
                "message": "The resource couldn't be listed"}}
        try:
            response = requests.get(url + self.auth + query_string,
                headers=ACCEPT_JSON, verify=VERIFY)

            code = response.status_code

            if code == HTTP_OK:
                resource = json.loads(response.content, 'utf-8')
                meta = resource['meta']
                resources = resource['objects']
                error = None
            elif code in [HTTP_BAD_REQUEST, HTTP_UNAUTHORIZED, HTTP_NOT_FOUND]:
                error = json.loads(response.content, 'utf-8')
            else:
                LOGGER.error("Unexpected error (%s)" % code)
                code = HTTP_INTERNAL_SERVER_ERROR

        except ValueError:
            LOGGER.error("Malformed response")
        except requests.ConnectionError:
            LOGGER.error("Connection error")
        except requests.Timeout:
            LOGGER.error("Request timed out")
        except requests.RequestException:
            LOGGER.error("Ambiguous exception occurred")

        return {
            'code': code,
            'meta': meta,
            'objects': resources,
            'error': error}

    def _update(self, url, body):
        """Updates a remote resource.

        Uses PUT to update a BigML resource. Only the new fields that
        are going to be updated need to be included in the `body`.

        Returns a resource wrapped in a dictionary:
            code: HTTP_ACCEPTED if the update has been OK or an error
                  code otherwise.
            resource: Resource/id
            location: Remote location of the resource.
            object: The new updated resource
            error: Error code if any. None otherwise

        """
        code = HTTP_INTERNAL_SERVER_ERROR
        resource_id = None
        location = url
        resource = None
        error = {
            "status": {
                "code": code,
                "message": "The resource couldn't be updated"}}

        try:
            response = requests.put(url + self.auth,
                headers=SEND_JSON,
                data=body, verify=VERIFY)

            code = response.status_code

            if code == HTTP_ACCEPTED:
                location = response.headers['location']
                resource = json.loads(response.content, 'utf-8')
                resource_id = resource['resource']
                error = None
            elif code in [
                HTTP_UNAUTHORIZED,
                HTTP_PAYMENT_REQUIRED,
                HTTP_METHOD_NOT_ALLOWED]:
                error = json.loads(response.content, 'utf-8')
            else:
                LOGGER.error("Unexpected error (%s)" % code)
                code = HTTP_INTERNAL_SERVER_ERROR

        except ValueError:
            LOGGER.error("Malformed response")
        except requests.ConnectionError:
            LOGGER.error("Connection error")
        except requests.Timeout:
            LOGGER.error("Request timed out")
        except requests.RequestException:
            LOGGER.error("Ambiguous exception occurred")

        return {
            'code': code,
            'resource': resource_id,
            'location': location,
            'object': resource,
            'error': error}

    def _delete(self, url):
        """Permanently deletes a remote resource.

        If the request is successful the status `code` will be HTTP_NO_CONTENT
        and `error` will be None. Otherwise, the `code` will be an error code and
        `error` will be provide a specific code and explanation.

        """
        code = HTTP_INTERNAL_SERVER_ERROR
        error = {
            "status": {
                "code": code,
                "message": "The resource couldn't be deleted"}}

        try:
            response = requests.delete(url + self.auth, verify=VERIFY)

            code = response.status_code

            if code == HTTP_NO_CONTENT:
                error = None
            elif code in [HTTP_BAD_REQUEST, HTTP_UNAUTHORIZED, HTTP_NOT_FOUND]:
                error = json.loads(response.content, 'utf-8')
            else:
                LOGGER.error("Unexpected error (%s)" % code)
                code = HTTP_INTERNAL_SERVER_ERROR

        except ValueError:
            LOGGER.error("Malformed response")
        except requests.ConnectionError:
            LOGGER.error("Connection error")
        except requests.Timeout:
            LOGGER.error("Request timed out")
        except requests.RequestException:
            LOGGER.error("Ambiguous exception occurred")


        return {
            'code': code,
            'error': error}

    ##########################################################################
    #
    # Utils
    #
    ##########################################################################
    def _is_valid_remote_url(self, value):
        """Returns True if value is a valid URL.

        """
        url = isinstance(value, basestring) and urlparse(value)
        return url and url.scheme and url.netloc and url.path

    def get_fields(self, resource):
        """Retrieve fields used by a resource.

        Returns a dictionary with the fields that uses
        the resource keyed by Id.

        """
        if isinstance(resource, dict) and 'resource' in resource:
            resource_id = resource['resource']
        elif (isinstance(resource, basestring) and (
             SOURCE_RE.match(resource) or DATASET_RE.match(resource) or
                MODEL_RE.match(resource) or PREDICTION_RE.match(resource))):
            resource_id = resource
        else:
            LOGGER.error("Wrong resource id")
            return

        resource = self._get("%s%s" % (self.URL, resource_id))
        if resource['code'] == HTTP_OK:
            if  MODEL_RE.match(resource_id):
                return resource['object']['model']['fields']
            else:
                return resource['object']['fields']
        return None

    def pprint(self, resource):
        """Pretty prints a resource or part of it.

        """

        pretty_print = pprint.PrettyPrinter(indent=4)
        if (isinstance(resource, dict) and
           'object' in resource and
           'resource' in resource):
            if SOURCE_RE.match(resource['resource']):
                print "%s (%s bytes)" % (resource['object']['name'],
                        resource['object']['size'])
            elif DATASET_RE.match(resource['resource']):
                print "%s (%s bytes)" % (resource['object']['name'],
                        resource['object']['size'])
            elif MODEL_RE.match(resource['resource']):
                print "%s (%s bytes)" % (resource['object']['name'],
                        resource['object']['size'])
            elif PREDICTION_RE.match(resource['resource']):
                objective_field_name = (
                    resource['object']['fields']
                        [resource['object']['objective_fields'][0]]['name'])
                input_data = dict(
                    [[resource['object']['fields'][key]['name'], value]
                        for key, value in
                            resource['object']['input_data'].items()])
                prediction = (
                    resource['object']['prediction']
                            [resource['object']['objective_fields'][0]])
                print("%s for %s is %s" % (objective_field_name, input_data,
                    prediction))
        else:
            pretty_print.pprint(resource)

    def status(self, resource):
        """Maps status code to string.

        """

        if isinstance(resource, dict) and 'resource' in resource:
            resource_id = resource['resource']
        elif (isinstance(resource, basestring) and (
             SOURCE_RE.match(resource) or DATASET_RE.match(resource) or
                MODEL_RE.match(resource) or PREDICTION_RE.match(resource))):
            resource_id = resource
        else:
            LOGGER.error("Wrong resource id")
            return

        resource = self._get("%s%s" % (self.URL, resource_id))
        code = resource['object']['status']['code']
        if code in STATUSES:
            return STATUSES[code]
        else:
            return "UNKNOWN"

    ##########################################################################
    #
    # Sources
    # https://bigml.com/developers/sources
    #
    ##########################################################################
    def _create_remote_source(self, url, args=None):
        """Creates a new source using a URL

        """
        if args is None:
            args = {}
        args.update({"remote": url})
        body = json.dumps(args)
        return self._create(self.SOURCE_URL, body)

    def _create_local_source(self, file_name, args=None):
        """Creates a new source using a local file.

        This function is now DEPRECATED as "requests" do not stream the file
        content what limited the size of local files to a small number of GBs.

        """
        if args is None:
            args = {}
        elif 'source_parser' in args:
            args['source_parser'] = json.dumps(args['source_parser'])

        code = HTTP_INTERNAL_SERVER_ERROR
        resource_id = None
        location = None
        resource = None
        error = {
            "status": {
                "code": code,
                "message": "The resource couldn't be created"}}

        files = {os.path.basename(file_name): open(file_name, "rb")}
        try:
            response = requests.post(self.SOURCE_URL + self.auth,
                                     files=files,
                                     data=args, verify=VERIFY)

            code = response.status_code

            if code == HTTP_CREATED:
                location = response.headers['location']
                resource = json.loads(response.content, 'utf-8')
                resource_id = resource['resource']
                error = None
            elif code in [
                HTTP_BAD_REQUEST,
                HTTP_UNAUTHORIZED,
                HTTP_PAYMENT_REQUIRED,
                HTTP_NOT_FOUND]:
                error = json.loads(response.content, 'utf-8')
            else:
                LOGGER.error("Unexpected error (%s)" % code)
                code = HTTP_INTERNAL_SERVER_ERROR

        except ValueError:
            LOGGER.error("Malformed response")
        except requests.ConnectionError:
            LOGGER.error("Connection error")
        except requests.Timeout:
            LOGGER.error("Request timed out")
        except requests.RequestException:
            LOGGER.error("Ambiguous exception occurred")

        return {
            'code': code,
            'resource': resource_id,
            'location': location,
            'object': resource,
            'error': error}

    def _upload_source(self, url, args, source):
        """Uploads a source asynchronously.

        """

        def update_progress(param, current, total):
            progress = round(current * 1.0 / total, 2)
            if progress < 1.0:
                source['progress'] = progress

        code = HTTP_INTERNAL_SERVER_ERROR
        error = {
            "status": {
                "code": code,
                "message": "The resource couldn't be created"}}

        body, headers = multipart_encode(args, cb=update_progress)
        request = urllib2.Request(url, body, headers)

        try:
            response = urllib2.urlopen(request)
            code = response.getcode()
            if code == HTTP_CREATED:
                location = response.headers['location']
                content = response.read()
                resource = json.loads(content, 'utf-8')
                resource_id = resource['resource']
                error = None
        except ValueError:
            LOGGER.error("Malformed response")
        except urllib2.HTTPError, exception:
            LOGGER.error("Error %s", exception.code)
            code = exception.code
            if code in [
                HTTP_BAD_REQUEST,
                HTTP_UNAUTHORIZED,
                HTTP_PAYMENT_REQUIRED,
                HTTP_NOT_FOUND]:
                content = exception.read()
                error = json.loads(content, 'utf-8')
            else:
                LOGGER.error("Unexpected error (%s)" % code)
                code = HTTP_INTERNAL_SERVER_ERROR

        except urllib2.URLError, exception:
            LOGGER.error("Error establishing connection")
            error = exception.args
        source['code'] = code
        source['resource'] = resource_id
        source['location'] = location
        source['object'] = resource
        source['error'] = error
        source['progress'] = 1.0

    def _stream_source(self, file_name, args=None, async=False):
        """Creates a new source.

        """
        def clear_progress_bar():
            sys.stdout.write("%s" % (" " * PROGRESS_BAR_WIDTH))
            sys.stdout.flush()

        def reset_progress_bar():
            sys.stdout.write("\b" * (PROGRESS_BAR_WIDTH+1))
            sys.stdout.flush()

        def draw_progress_bar(param, current, total):
            pct = 100 - ((total - current ) * 100 ) / (total)
            progress = round(pct * 1.0 / 100, 2)
            clear_progress_bar()
            reset_progress_bar()
            sys.stdout.write("Uploaded %s out of %s [%s%%]" % (current, total, pct))
            reset_progress_bar()
            sys.stdout.flush()

        if args is None:
            args = {}
        elif 'source_parser' in args:
            args['source_parser'] = json.dumps(args['source_parser'])

        code = HTTP_INTERNAL_SERVER_ERROR
        resource_id = None
        location = None
        resource = None
        error = None

        if async:
            args.update({os.path.basename(file_name): open(file_name, "rb")})
            source = {
                'code': HTTP_ACCEPTED,
                'resource': resource_id,
                'location': location,
                'object': resource,
                'error': error,
                'progress': 0.0}
            upload_args = (self.SOURCE_URL + self.auth, args, source)
            t = Thread(target=self._upload_source, args=upload_args, kwargs={})
            t.start()
            return source

        error = {
            "status": {
                "code": code,
                "message": "The resource couldn't be created"}}

        args.update({os.path.basename(file_name): open(file_name, "rb")})
        body, headers = multipart_encode(args, cb=draw_progress_bar)
        request = urllib2.Request(self.SOURCE_URL + self.auth, body, headers)
        try:
            response = urllib2.urlopen(request)
            clear_progress_bar()
            reset_progress_bar()
            code = response.getcode()
            if code == HTTP_CREATED:
                location = response.headers['location']
                content = response.read()
                resource = json.loads(content, 'utf-8')
                resource_id = resource['resource']
                error = {}
        except ValueError:
            LOGGER.error("Malformed response")
        except urllib2.HTTPError, exception:
            LOGGER.error("Error %s", exception.code)
            code = exception.code
            if code in [
                HTTP_BAD_REQUEST,
                HTTP_UNAUTHORIZED,
                HTTP_PAYMENT_REQUIRED,
                HTTP_NOT_FOUND]:
                content = exception.read()
                error = json.loads(content, 'utf-8')
            else:
                LOGGER.error("Unexpected error (%s)" % code)
                code = HTTP_INTERNAL_SERVER_ERROR

        except urllib2.URLError, exception:
            LOGGER.error("Error establishing connection")
            error = exception.args
        return {
            'code': code,
            'resource': resource_id,
            'location': location,
            'object': resource,
            'error': error,
            'progress': 1.0}

    def create_source(self, path=None, args=None, async=False):
        """Creates a new source.

           The source can be a local file path or a URL.

        """

        if path is None:
            raise Exception('A local path or a valid URL must be provided.')

        if self._is_valid_remote_url(path):
            return self._create_remote_source(url=path, args=args)
        else:
            return self._stream_source(file_name=path, args=args, async=async)

    def _get_source_id(self, source):
        """Returns a source/id.
        """
        if isinstance(source, dict) and 'resource' in source:
            return source['resource']
        elif isinstance(source, basestring) and SOURCE_RE.match(source):
            return source
        else:
            LOGGER.error("Wrong source id")

    def get_source(self, source):
        """Retrieves a remote source.

        """
        source_id = self._get_source_id(source)
        if source_id:
            return self._get("%s%s" % (self.URL, source_id))

    def source_is_ready(self, source):
        """Checks whether a source' status is FINISHED.

        """
        source = self.get_source(source)
        return (source['code'] == HTTP_OK and
            source['object']['status']['code'] == FINISHED)

    def list_sources(self, query_string=''):
        """Lists all your remote sources.

        """
        return self._list(self.SOURCE_URL, query_string)

    def update_source(self, source, changes):
        """Updates a source.

        Updates remote `source` with `changes'.

        """
        source_id = self._get_source_id(source)
        if source_id:
            body = json.dumps(changes)
            return self._update("%s%s" % (self.URL, source_id), body)

    def delete_source(self, source):
        """Deletes a remote source permanently.

        """
        source_id = self._get_source_id(source)
        if source_id:
            return self._delete("%s%s" % (self.URL, source_id))

    ##########################################################################
    #
    # Datasets
    # https://bigml.com/developers/datasets
    #
    ##########################################################################
    def create_dataset(self, source, args=None, wait_time=3):
        """Creates a remote dataset.

        Uses remote `source` to create a new dataset using the arguments in
        `args`.  If `wait_time` is higgher than 0 then the dataset creation
        request is not sent until the `source` has been created successfuly.

        """
        source_id = self._get_source_id(source)
        if source_id:
            if wait_time > 0:
                while not self.source_is_ready(source_id):
                    time.sleep(wait_time)

            if args is None:
                args = {}
            args.update({
                "source": source_id})
            body = json.dumps(args)
            return self._create(self.DATASET_URL, body)

    def _get_dataset_id(self, dataset):
        """Returns a dataset/id.

        """
        if isinstance(dataset, dict) and 'resource' in dataset:
            return dataset['resource']
        elif isinstance(dataset, basestring) and DATASET_RE.match(dataset):
            return dataset
        else:
            LOGGER.error("Wrong dataset id")

    def get_dataset(self, dataset):
        """Retrieves a dataset.

        """
        dataset_id = self._get_dataset_id(dataset)
        if dataset_id:
            return self._get("%s%s" % (self.URL, dataset_id))

    def dataset_is_ready(self, dataset):
        """Check whether a dataset' status is FINISHED.

        """
        resource = self.get_dataset(dataset)
        return (resource['code'] == HTTP_OK and
            resource['object']['status']['code'] == FINISHED)

    def list_datasets(self, query_string=''):
        """Lists all your datasets.

        """
        return self._list(self.DATASET_URL, query_string)

    def update_dataset(self, dataset, changes):
        """Updates a dataset.

        """
        dataset_id = self._get_dataset_id(dataset)
        if dataset_id:
            body = json.dumps(changes)
            return self._update("%s%s" % (self.URL, dataset_id), body)

    def delete_dataset(self, dataset):
        """Deletes a dataset.

        """
        dataset_id = self._get_dataset_id(dataset)
        if dataset_id:
            return self._delete("%s%s" % (self.URL, dataset_id))

    ##########################################################################
    #
    # Models
    # https://bigml.com/developers/models
    #
    ##########################################################################
    def create_model(self, dataset, args=None, wait_time=3):
        """Creates a model.

        """
        dataset_id = self._get_dataset_id(dataset)

        if dataset_id:
            if wait_time > 0:
                while not self.dataset_is_ready(dataset_id):
                    time.sleep(wait_time)

            if args is None:
                args = {}
            args.update({
                "dataset": dataset_id})
            body = json.dumps(args)
            return self._create(self.MODEL_URL, body)

    def _get_model_id(self, model):
        """Returns a a model/id.

        """
        if isinstance(model, dict) and 'resource' in model:
            return model['resource']
        elif isinstance(model, basestring) and MODEL_RE.match(model):
            return model
        else:
            LOGGER.error("Wrong model id")

    def get_model(self, model):
        """Retrieves a model.

        """
        model_id = self._get_model_id(model)
        if model_id:
            return self._get("%s%s" % (self.URL, model_id))

    def model_is_ready(self, model):
        """Checks whether a model's status is FINISHED.

        """
        resource = self.get_model(model)
        return (resource['code'] == HTTP_OK and
            resource['object']['status']['code'] == FINISHED)

    def list_models(self, query_string=''):
        """Lists all your models.

        """
        return self._list(self.MODEL_URL, query_string)

    def update_model(self, model, changes):
        """Updates a model.

        """
        model_id = self._get_model_id(model)
        if model_id:
            body = json.dumps(changes)
            return self._update("%s%s" % (self.URL, model_id), body)

    def delete_model(self, model):
        """Deletes a model.

        """
        model_id = self._get_model_id(model)
        if model_id:
            return self._delete("%s%s" % (self.URL, model_id))

    ##########################################################################
    #
    # Predictions
    # https://bigml.com/developers/predictions
    #
    ##########################################################################
    def create_prediction(self, model, input_data=None, args=None,
            wait_time=3):
        """Creates a new prediction.

        """
        model_id = self._get_model_id(model)

        if model_id:
            if wait_time > 0:
                while not self.model_is_ready(model_id):
                    time.sleep(wait_time)

            if input_data is None:
                input_data = {}
            else:
                fields = self.get_fields(model_id)
                inverted_fields = invert_dictionary(fields)
                try:
                    input_data = dict(
                        [[inverted_fields[key], value]
                         for key, value in input_data.items()])
                except KeyError, field:
                    LOGGER.error("Wrong field name %s" % field)

            if args is None:
                args = {}
            args.update({
                "model": model_id,
                "input_data": input_data})
            body = json.dumps(args)
            return self._create(self.PREDICTION_URL, body)

    def _get_prediction_id(self, prediction):
        """Returns a prediction/id.

        """
        if isinstance(prediction, dict) and 'resource' in prediction:
            return prediction['resource']
        elif (isinstance(prediction, basestring) and
              PREDICTION_RE.match(prediction)):
            return prediction
        else:
            LOGGER.error("Wrong prediction id")

    def get_prediction(self, prediction):
        """Retrieves a prediction.

        """
        prediction_id = self._get_prediction_id(prediction)
        if prediction_id:
            return self._get("%s%s" % (self.URL, prediction_id))

    def list_predictions(self, query_string=''):
        """Lists all your predictions.

        """
        return self._list(self.PREDICTION_URL, query_string)

    def update_prediction(self, prediction, changes):
        """Updates a prediction.

        """
        prediction_id = self._get_prediction_id(prediction)
        if prediction_id:
            body = json.dumps(changes)
            return self._update("%s%s" % (self.URL, prediction_id), body)

    def delete_prediction(self, prediction):
        """Deletes a prediction.

        """
        prediction_id = self._get_prediction_id(prediction)
        if prediction_id:
            return self._delete("%s%s" %
                (self.URL, prediction_id))
