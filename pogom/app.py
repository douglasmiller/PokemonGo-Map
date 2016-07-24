#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging

from flask import Flask, jsonify, render_template, request, make_response
from flask.json import JSONEncoder
from flask_compress import Compress
from datetime import datetime
from s2sphere import *
from pogom.utils import get_args, datetime_to_miliseconds

from protobuf_to_dict import dict_to_protobuf
import pogom.protos.PogomResponse_pb2 as PogomResponse

from . import config
from .models import Pokemon, Gym, Pokestop, ScannedLocation

log = logging.getLogger(__name__)
compress = Compress()

class Pogom(Flask):
    def __init__(self, import_name, **kwargs):
        super(Pogom, self).__init__(import_name, **kwargs)
        compress.init_app(self)
        self.json_encoder = CustomJSONEncoder
        self.route("/", methods=['GET'])(self.fullmap)
        self.route("/raw_data", methods=['GET'])(self.raw_data)
        self.route("/proto_data", methods=['GET'])(self.proto_data)
        self.route("/loc", methods=['GET'])(self.loc)
        self.route("/next_loc", methods=['POST'])(self.next_loc)
        self.route("/mobile", methods=['GET'])(self.list_pokemon)

    def fullmap(self):
        args = get_args()
        display = "inline"
        if args.fixed_location:
            display = "none"
        
        return render_template('map.html',
                               lat=config['ORIGINAL_LATITUDE'],
                               lng=config['ORIGINAL_LONGITUDE'],
                               gmaps_key=config['GMAPS_KEY'],
                               lang=config['LOCALE'],
                               is_fixed=display
                               )

    def get_raw_data(self, convert=False):
        d = {}
        bounds = {
            'swLat': request.args.get('swLat'),
            'swLng': request.args.get('swLng'),
            'neLat': request.args.get('neLat'),
            'neLng': request.args.get('neLng')
        }
        if request.args.get('pokemon', 'true') == 'true':
            if request.args.get('ids'):
                ids = [int(x) for x in request.args.get('ids').split(',')]
                d['pokemons'] = Pokemon.get_active_by_id(ids, bounds, convert)
            else:
                d['pokemons'] = Pokemon.get_active(bounds, convert)

        if request.args.get('pokestops', 'false') == 'true':
            d['pokestops'] = Pokestop.get_stops(bounds, convert)

        if request.args.get('gyms', 'true') == 'true':
            d['gyms'] = Gym.get_gyms(bounds, convert)

        if request.args.get('scanned', 'true') == 'true':
            d['scanned'] = ScannedLocation.get_recent(bounds, convert)

        return d


    def raw_data(self):
        return jsonify(self.get_raw_data())

    def proto_data(self):
        proto = dict_to_protobuf(PogomResponse.Response, self.get_raw_data(True))

        res = make_response(proto.SerializeToString())
        res.headers.set('Content-Type', 'application/octet-stream')

        return res

    def loc(self):
        d = {}
        d['lat']=config['ORIGINAL_LATITUDE']
        d['lng']=config['ORIGINAL_LONGITUDE']

        return jsonify(d)

    def next_loc(self):
        args = get_args()
        if args.fixed_location:
            return 'Location searching is turned off', 403
       #part of query string
        if request.args:
            lat = request.args.get('lat', type=float)
            lon = request.args.get('lon', type=float)
        #from post requests
        if request.form:
            lat = request.form.get('lat', type=float)
            lon = request.form.get('lon', type=float)

        if not (lat and lon):
            log.warning('Invalid next location: %s,%s' % (lat, lon))
            return 'bad parameters', 400
        else:
            config['NEXT_LOCATION'] = {'lat': lat, 'lon': lon}
            log.info('Changing next location: %s,%s' % (lat, lon))
            return 'ok'

    def list_pokemon(self):
        # todo: check if client is android/iOS/Desktop for geolink, currently only supports android
        pokemon_list = []
        origin_point = LatLng.from_degrees(config['ORIGINAL_LATITUDE'], config['ORIGINAL_LONGITUDE'])
        for pokemon in Pokemon.get_active():
            pokemon_point = LatLng.from_degrees(pokemon['latitude'], pokemon['longitude'])
            diff = pokemon_point - origin_point
            diff_lat = diff.lat().degrees
            diff_lng = diff.lng().degrees
            direction = (('N' if diff_lat >= 0 else 'S') if abs(diff_lat) > 1e-4 else '') + (
                ('E' if diff_lng >= 0 else 'W') if abs(diff_lng) > 1e-4 else '')
            entry = {
                'id': pokemon['pokemon_id'],
                'name': pokemon['pokemon_name'],
                'card_dir': direction,
                'distance': int(origin_point.get_distance(pokemon_point).radians * 6366468.241830914),
                'time_to_disappear': '%dm %ds' % (divmod((pokemon['disappear_time']-datetime.utcnow()).seconds, 60)),
                'latitude': pokemon['latitude'],
                'longitude': pokemon['longitude']
            }
            pokemon_list.append((entry, entry['distance']))
        pokemon_list = [y[0] for y in sorted(pokemon_list, key=lambda x: x[1])]
        return render_template('mobile_list.html',
                               pokemon_list=pokemon_list,
                               origin_lat=config['ORIGINAL_LATITUDE'],
                               origin_lng=config['ORIGINAL_LONGITUDE'])


class CustomJSONEncoder(JSONEncoder):

    def default(self, obj):
        try:
            if isinstance(obj, datetime):
                datetime_to_miliseconds(obj)
            iterable = iter(obj)
        except TypeError:
            pass
        else:
            return list(iterable)
        return JSONEncoder.default(self, obj)
