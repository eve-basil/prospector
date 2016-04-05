import logging
import os

try:
    from functools import lru_cache
except ImportError:
    from backports.functools_lru_cache import lru_cache

import eveapi
import requests

from basil_common.configurables import verify
from basil.market.prospect import prospect as prospects
from basil.industry import IndustryException


LOG = logging.getLogger(__name__)
logging.getLogger('requests').level = logging.WARNING

REQUIRED_OPS = ['REDIS_HOST', 'EVE_API_KEY', 'EVE_API_VCODE', 'REFAPI_URL',
                'STATION_IDS', 'PRICES_URL', 'WATCHES_URL']


def grouped_prints(auth, character_key=False):
    if character_key:
        path = auth.char
    else:
        path = auth.corp
    prints = path.Blueprints().blueprints
    keys = prints.Select('typeID')
    grouped = prints.GroupedBy('typeID')
    return keys, grouped


def collected_prints(auth, character_key=False):
    if character_key:
        path = auth.char
    else:
        path = auth.corp
    prints = path.Blueprints().blueprints
    keys = prints.Select('typeID')
    grouped = prints.GroupedBy('typeID')
    return list(keys), grouped


def blueprint_from(bp, recipe):
    blueprint = {k: bp[k] for k in bp._cols}
    blueprint.update(recipe)
    return blueprint


def evaluate_prospects(refapi, facilities, print_keys, print_groups):
    prospects = []
    for key in set(print_keys):
        product = print_groups[key]
        result = evaluate_product(refapi, facilities, product)
        if not result:
            continue
        prospects.append(result)
    return prospects


def evaluate_product(refapi, facilities, product):
    material_efficiencies = set(product.Select('materialEfficiency'))
    copies_by_me = product.GroupedBy('materialEfficiency')
    for me_value in material_efficiencies:
        # don't evaluate un-researched prints
        if me_value > 3:
            copies = len(copies_by_me[me_value])
            bp = copies_by_me[me_value][0]
            recipe = refapi('recipes/manufacturing/%s' % bp.typeID)
            blueprint = blueprint_from(bp, recipe)
            try:
                this_prospect = prospects(blueprint, facilities, 1, copies)
            except IndustryException:
                return None
            if this_prospect[0].profit_margin > 5.0:
                return this_prospect
            else:
                # not worth our time, skip it and the rest
                break


def link_refapi(base_url):
    headers = {'user-agent': 'github.com/eve-basil/printer[0.1.0-dev]'}
    session = requests.Session()
    session.headers.update(headers)

    @lru_cache(maxsize=24)
    def refapi(url_path, **kwargs):
        url = base_url + url_path
        return session.get(url, **kwargs).json()

    return refapi


def filter_by_quality(output):
    passing = [i[0] for i in output if len(i) > 0 and
               i[0].profit_per_run > 30000]
    passing.sort(key=lambda prosp: prosp.profit_per_run)
    return passing


def main():
    verify(REQUIRED_OPS)

    auth = authorized_api()
    prints_keys, prints_groups = grouped_prints(auth)
    evaluation = evaluate_prospects(link_refapi(os.environ['REFAPI_URL']),
                                    lookup_facilities(), prints_keys,
                                    prints_groups)
    options = as_json(filter_by_quality(evaluation))
    import json
    print "options: %s" % len(options)
    print json.dumps(options, indent=2)


def authorized_api():
    api = eveapi.EVEAPIConnection()
    auth = api.auth(keyID=os.environ['EVE_API_KEY'],
                    vCode=os.environ['EVE_API_VCODE'])
    return auth


def as_json(results):
    options = []
    for prospect in results:
        opt = {'product': prospect.product,
               'copies': prospect.count,
               'location': prospect.facility.name.split(' ', 1),
               'blueprint_me': prospect.blueprint_me,
               'price': prospect.price_per_unit,
               'cost': prospect.cost_per_unit,
               'profit': prospect.profit_per_unit,
               'margin': prospect.profit_margin,
               'install': prospect.install_cost,
               'materials': prospect.materials.as_dict()}
        options.append(opt)

    return options


def lookup_facilities():
    from basil.industry.facility import facility
    stations = os.environ['STATION_IDS'].split(',')
    return [facility(fac_id) for fac_id in stations]


if __name__ == "__main__":
    main()
