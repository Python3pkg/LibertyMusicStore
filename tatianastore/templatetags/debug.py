# -*- coding: utf-8 -*-
#
# http://djangosnippets.org/snippets/1550/
#

try:
    import ipdb as pdb_module
except ImportError:
    import pdb as pdb_module

from django.template import Library, Node

register = Library()

class PdbNode(Node):

    def render(self, context):
        for d in context.dicts:
            print((list(d.keys())))
        pdb_module.set_trace()
        return ''

@register.tag
def pdb(parser, token):
    return PdbNode()
