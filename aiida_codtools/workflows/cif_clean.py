# -*- coding: utf-8 -*-
from aiida.common.extendeddicts import AttributeDict
from aiida.orm import Code, Group
from aiida.orm.data.cif import CifData
from aiida.orm.data.base import Float, Str
from aiida.orm.data.parameter import ParameterData
from aiida.orm.data.structure import StructureData
from aiida.orm.utils import CalculationFactory
from aiida.tools import get_kpoints_path
from aiida.work.workchain import WorkChain, ToContext, if_
from aiida.work.workfunctions import workfunction


CifFilterCalculation = CalculationFactory('codtools.cif_filter')
CifSelectCalculation = CalculationFactory('codtools.cif_select')


class CifCleanWorkChain(WorkChain):
    """
    WorkChain to clean a CifData node using the cif_filter and cif_select scripts of cod-tools
    It will first run cif_filter to correct syntax errors, followed by cif_select which will remove
    various tags and canonicalize the remaining tags. If a group is passed for the group_structure
    input, ASE will be used to parse the final cleaned CifData to construct a StructureData object
    which will then be passed to the SeeKpath library to analyze it and return the primitive structure
    """

    ERROR_CIF_FILTER_FAILED = 1
    ERROR_CIF_SELECT_FAILED = 2
    ERROR_SEEKPATH_FAILED = 3

    @classmethod
    def define(cls, spec):
        super(CifCleanWorkChain, cls).define(spec)
        spec.input('cif', valid_type=CifData,
            help='the CifData node that is to be cleaned')
        spec.input('cif_filter', valid_type=Code,
            help='the AiiDA code object that references the cod-tools cif_filter script')
        spec.input('cif_select', valid_type=Code,
            help='the AiiDA code object that references the cod-tools cif_select script')
        spec.input('options', valid_type=ParameterData,
            help='options for the calculations')
        spec.input('tags', valid_type=Str, default=Str('_publ_author_name,_citation_journal_abbrev'),
            help='comma separated tag names that are to be removed by the cif_select step')
        spec.input('symprec', valid_type=Float, default=Float(5E-3),
            help='the symmetry precision used by SeeK-path for crystal symmetry refinement')
        spec.input('group_cif', valid_type=Group, required=False, non_db=True,
            help='an optional Group to which the final cleaned CifData node will be added')
        spec.input('group_structure', valid_type=Group, required=False, non_db=True,
            help='an optional Group to which the final reduced StructureData node will be added')
        spec.outline(
            cls.run_filter_calculation,
            cls.inspect_filter_calculation,
            cls.run_select_calculation,
            cls.inspect_select_calculation,
            if_(cls.should_create_structure)(
                cls.create_reduced_structure,
            ),
            cls.results,
        )
        spec.output('cif', valid_type=CifData,
            help='the cleaned CifData node')
        spec.output('structure', valid_type=StructureData, required=False,
            help='the primitive cell structure created with SeeK-path from the cleaned CifData')

    def run_filter_calculation(self):
        """
        Run the CifFilterCalculation on the CifData input node
        """
        parameters = {
            'use-perl-parser': True,
            'fix-syntax-errors': True,
        }

        inputs = AttributeDict({
            'cif': self.inputs.cif,
            'code': self.inputs.cif_filter,
            'parameters': ParameterData(dict=parameters),
            'options': self.inputs.options.get_dict(),
        })

        process = CifFilterCalculation.process()
        running = self.submit(process, **inputs)

        self.report('submitted {}<{}>'.format(CifFilterCalculation.__name__, running.pk))

        return ToContext(cif_filter=running)

    def inspect_filter_calculation(self):
        """
        Inspect the result of the CifFilterCalculation, verifying that it produced a CifData output node
        """
        try:
            self.ctx.cif = self.ctx.cif_filter.out.cif
        except AttributeError:
            self.report('aborting: the CifFilterCalculation did not return the required cif output')
            return self.ERROR_CIF_FILTER_FAILED

    def run_select_calculation(self):
        """
        Run the CifSelectCalculation on the CifData output node of the CifFilterCalculation
        """
        parameters = {
            'use-perl-parser': True,
            'canonicalize-tag-names': True,
            'invert': True,
            'tags': self.inputs.tags.value,
        }

        inputs = AttributeDict({
            'cif': self.ctx.cif,
            'code': self.inputs.cif_select,
            'parameters': ParameterData(dict=parameters),
            'options': self.inputs.options.get_dict(),
        })

        process = CifSelectCalculation.process()
        running = self.submit(process, **inputs)

        self.report('submitted {}<{}>'.format(CifSelectCalculation.__name__, running.pk))

        return ToContext(cif_select=running)

    def inspect_select_calculation(self):
        """
        Inspect the result of the CifSelectCalculation, verifying that it produced a CifData output node
        """
        try:
            self.ctx.cif = self.ctx.cif_select.out.cif
        except AttributeError:
            self.report('aborting: the CifSelectCalculation did not return the required cif output')
            return self.ERROR_CIF_SELECT_FAILED

    def should_create_structure(self):
        """
        Return whether the primitive structure should be created from the final cleaned CifData
        Will be true if the 'group_structure' input is specified
        """
        return 'group_structure' in self.inputs

    def create_reduced_structure(self):
        """
        Create a StructureData from the CifData output node returned by the CifSelectCalculation and
        find the primitive cell structure through the SeeK-path library
        """
        result = cif_reduce_seekpath(self.ctx.cif, self.inputs.symprec)

        try:
            self.ctx.structure = result['primitive_structure']
        except AttributeError:
            self.report('aborting: SeeKpath did not return a primitive structure')
            return self.ERROR_SEEKPATH_FAILED

    def results(self):
        """
        The filter and select calculations were successful, so we return the desired output nodes
        """
        returned_nodes = []

        if 'group_cif' in self.inputs:
            cif = self.ctx.cif
            self.inputs.group_cif.add_nodes([cif])
            self.out('cif', cif)
            returned_nodes.append('CifData<{}>'.format(cif.pk))

        if 'group_structure' in self.inputs:
            structure = self.ctx.structure
            self.inputs.group_structure.add_nodes([structure])
            self.out('structure', structure)
            returned_nodes.append('StructureData<{}>'.format(structure.pk))


        self.report('workchain finished successfully, returned nodes {}'.format(', '.join(returned_nodes)))


@workfunction
def cif_reduce_seekpath(cif, symprec):
    """
    This workfunction will take a CifData node, create a StructureData object from it
    and pass it through SeeKpath to get the primitive cell
    """
    structure = StructureData(ase=cif.get_ase())
    return get_kpoints_path(structure, symprec=symprec) 