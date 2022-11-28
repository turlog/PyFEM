import sys
import re


def merge(a, b, path=None):
    if b is None:
        return a
    if path is None:
        path = []
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                merge(a[key], b[key], path + [str(key)])
            elif a[key] == b[key]:
                pass
            elif isinstance(a[key], list) and isinstance(b[key], list):
                a[key].extend(b[key])
            else:
                raise ValueError('Conflict at %s' % '.'.join(path + [str(key)]))
        else:
            a[key] = b[key]
    return a


def parse_row(row, spec):
    return (cast(token) for cast, token in zip(spec, row.split()))


class Parser:

    __ignored_blocks = {
        'KEYWORD',
        'CONTROL_ACCURACY',
        'CONTROL_IMPLICIT_AUTO',
        'CONTROL_IMPLICIT_DYNAMICS',
        'CONTROL_IMPLICIT_GENERAL',
        'CONTROL_IMPLICIT_SOLUTION',
        'CONTROL_TERMINATION',
        'DATABASE_BNDOUT',
        'DATABASE_ELOUT',
        'DATABASE_GCEOUT',
        'DATABASE_GLSTAT',
        'DATABASE_MATSUM',
        'DATABASE_NCFORC',
        'DATABASE_NODFOR',
        'DATABASE_NODOUT',
        'DATABASE_RCFORC',
        'DATABASE_RWFORC',
        'DATABASE_SECFORC',
        'DATABASE_SLEOUT',
        'DATABASE_SPCFORC',
        'DATABASE_SWFORC',
        'DATABASE_BINARY_D',
        'DATABASE_EXTENT_BINARY',
        'ELEMENT_SHELL',
        'SECTION_SHELL_TITLE',
        'MAT_ELASTIC_TITLE',
        'MAT_PIECEWISE_LINEAR_PLASTICITY_TITLE',
        'PART',
        'SECTION_SOLID_TITLE',
        'SET_SEGMENT_TITLE',
        'LOAD_SEGMENT_SET_ID',
        'END',
    }

    def __init__(self):
        self.context = {}

    def parse_title(self, data):
        return {
            'title': data[0]
        }

    def parse_node(self, data):
        nodes = {}
        for row in data:
            nid, x, y, z = parse_row(row, (int, float, float, float))
            nodes[int(nid)] = (x, y, z)
        return {
            'nodes': nodes
        }

    def parse_define_curve_title(self, data):
        curve = {
            'title': data[0],
            **dict(zip(
                ('lcid', 'sidr', 'sfa', 'sfo', 'offa', 'offo', 'dattyp', 'lcint'),
                parse_row(data[1], (int, int, float, float, float, float, int, int)))),
            'points': [[*map(float, row.split())] for row in data[2:]]
        }
        return {
            'curves': {
                curve.pop('lcid'): curve
            }
        }

    def parse_boundary_spc_set_id(self, data):
        return {
            'boundary': {
                data[0][1:]: dict(zip(
                    ('nsid', 'cid', 'dofx', 'dofy', 'dofz', 'dofrx', 'dofry', 'dofrz'),
                    map(int, data[1].split())
                ))
            }
        }

    def parse_set_node_list_title(self, data):
        # workaround for no whitespace between da4 and solver
        data[1] = re.sub(r'([0-9])([A-Z]+)$', '\\1 \\2', data[1])
        nodelist = {
            'title': data[0],
            **dict(zip(
                ('sid', 'da1', 'da2', 'da3', 'da4', 'solver'),
                parse_row(data[1], (int, float, float, float, float, str))
            )),
            'nodes': [node for row in data[2:] for node in map(int, row.split()) if node]
        }
        return {
            'nodelist': {
                nodelist.pop('sid'): nodelist
            }
        }

    def parse_element_solid(self, data):
        items = {}
        for row in data:
            eid, _, *nodes = parse_row(row, (int, int, *([int]*8)))
            items[eid] = nodes
        return {
            'elements': {
                'solid': items
            }
        }

    def parse_load_node_set(self, data):
        nodesets = {}
        for row in data:
            nodeset = dict(zip(
                ('nsid', 'dof', 'lcid', 'sf', 'cid', 'm1', 'm2', 'm3'),
                parse_row(row, (int, int, int, float, int, int, int, int))
            ))
            nodesets[nodeset.pop('nsid')] = nodeset
        return {
            'nodesets': nodesets
        }

    def parse(self, name, data):
        method = getattr(self, f'parse_{name.lower()}', None)
        if callable(method):
            return method(data)
        if name not in self.__ignored_blocks:
            raise ValueError(f'Unknown block: "{name}"')


with open(sys.argv[1], 'rt') as infile:

    blocks = []

    comment_pattern = re.compile(r'^\s*\$#\s*(.*)')
    block_pattern = re.compile(r'^\*([A-Z_]+)')

    for line in infile:
        if comment_pattern.match(line):
            continue
        match = block_pattern.match(line)
        if match is not None:
            blocks.append([match.group(1)])
        else:
            blocks[-1].append(line.strip())

    model = {}
    parser = Parser()

    for name, *data in blocks:
        merge(model, parser.parse(name, data))

    print('<Nodes>')
    for nid, (x, y, z) in model['nodes'].items():
        print(f'{nid} {x} {y} {z};')
    print('</Nodes>')

    print('<Elements>')
    for eid, n in model.get('elements', {}).get('solid', {}).items():
        print(f"{eid} 'Continuum' {' '.join(map(str, n))};")
    print('</Elements>')

    for nodelist in model['nodelist'].values():
        print(f'<NodeGroup name = "{nodelist["title"]}">')
        print(f"{{ {' '.join(map(str, nodelist['nodes']))} }}")
        print('</NodeGroup>')

    print('<NodeConstraints>')
    for name, cond in model['boundary'].items():
        for ax, field in {'u': 'dofx', 'v': 'dofy', 'w': 'dofz'}.items():
            print(f'{ax}[{name}] = {0.0 if cond[field] else 1.0};')
    print('</NodeConstraints>')

    print('<ExternalForces>')
    for nsid, nodeset in model.get('nodesets', {}).items():
        force = model['curves'][nodeset['lcid']]['sfo']
        coord = {1: 'u', 2: 'v', 3: 'w'}[nodeset['lcid']]
        for node in model['nodelist'][nsid]['nodes']:
            print(f'{coord}[{node}] = {force};')
    print('</ExternalForces>')
