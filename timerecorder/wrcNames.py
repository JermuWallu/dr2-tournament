'''
Friendly names for the numeric ids EA WRC sends (route, location and vehicle).

The game identifies the stage and the car by number, not by name. Known ids live in
`resources/wrc-names.json`, which you can extend by hand; anything missing falls back to
"Route 12345" / "Car 103", and the admin portal can rename a track or car afterwards.
'''
import json
import os

from .log import getLogger

logger = getLogger(__name__)

NAMES_FILE = os.path.join('resources', 'wrc-names.json')

class WrcNames():

    def __init__(self, routes=None, locations=None, vehicles=None):
        self.routes = dict(routes or {})
        self.locations = dict(locations or {})
        self.vehicles = dict(vehicles or {})

    @classmethod
    def load(cls, approot):
        path = os.path.join(approot, NAMES_FILE)
        try:
            with open(path, encoding='utf-8') as file:
                data = json.load(file)
            names = cls(_keysToInt(data.get('routes')), _keysToInt(data.get('locations')),
                        _keysToInt(data.get('vehicles')))
            logger.debug('Loaded %s route and %s vehicle names', len(names.routes), len(names.vehicles))
            return names
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError, json.JSONDecodeError):
            logger.exception('Could not read %s, using numeric ids', path)
            return cls()

    def track(self, routeId, locationId=None):
        '''
        "Location - Route" when both are known, otherwise whichever is, otherwise the number.
        The route id alone identifies the stage, so it is always part of the fallback.
        '''
        route = self.routes.get(_asInt(routeId))
        location = self.locations.get(_asInt(locationId)) if locationId is not None else None

        if route and location and not route.startswith(location):
            return f'{location} - {route}'
        if route:
            return route
        if location:
            return f'{location} - Route {_asInt(routeId)}'
        return f'Route {_asInt(routeId)}'

    def car(self, vehicleId):
        return self.vehicles.get(_asInt(vehicleId)) or f'Car {_asInt(vehicleId)}'


def _asInt(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value

def _keysToInt(mapping):
    if not mapping:
        return {}
    converted = {}
    for key, value in mapping.items():
        converted[_asInt(key)] = value
    return converted
