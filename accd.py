#!/usr/bin/env python

import argparse
import copy
import imp
import os
import pprint
import sys

class AccdFailedException(Exception):
  pass

class ModuleCoverage:
  def __init__(self, sancov_path):
    name_components = os.path.basename(sancov_path).split('.')
    num_components = len(name_components)
    if num_components != 2 and num_components != 3:
      raise AccdFailedException('Bad sancov filename at ' + sancov_path)
    self.module = name_components[0]
    self.pid = int(name_components[1]) if num_components == 3 else -1
    self.offsets = sancov.ReadOneFile(sancov_path)

  def merge(self, other):
    self.offsets |= other.offsets

class Coverage:
  def __init__(self):
    self.modules = {}

  def merge_sancov_file(self, sancov_path):
    module = ModuleCoverage(sancov_path)
    self.merge_module(module)

  def merge_module(self, module):
    module_name = module.module
    if module_name in self.modules:
      self.modules[module_name].merge(module)
    else:
      self.modules[module_name] = copy.deepcopy(module)

class Accd:
  def parse_args(self):
    description      =  'Coverage tool based on ASAN coverage.'
    distilled_help   = ('Directory where to store the distilled corpus. '
                        'If it already exists, newly distilled testcases will be added.')
    undistilled_help =  'Input directory for undistilled testcases.'
    command_help     = ('The rest of the command line will be executed as a command that '
                        'processes a testcase. Testcase name can be referenced by %%testcase')
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('distilled', help=distilled_help)
    parser.add_argument('undistilled', help=undistilled_help)
    parser.add_argument('command', help=command_help, nargs=argparse.REMAINDER)
    self.parser = parser
    return parser.parse_args()

  def import_sancov(self):
    sancov_key = 'LLVM_PATH'
    if not sancov_key in os.environ:
      print 'Point LLVM_PATH environment variable to llvm source tree (necessary for sancov.py).'
      return False
    llvm_path = os.environ[sancov_key]
    sancov_module_path = os.path.join(llvm_path, 'projects', 'compiler-rt', 'lib', 'sanitizer_common',
                               'scripts', 'sancov.py')
    try:
      imp.load_source('sancov', sancov_module_path)
    except IOError:
      raise AccdFailedException('Failed to load ' + sancov_module_path)
    import sancov

  def read_existing_coverage(self):
    self.coverage_dir = os.path.join(self.distilled_dir, 'coverage')
    if os.path.isdir(self.coverage_dir):
      for filename in os.listdir(self.coverage_dir):
        sancov_path = os.path.join(self.coverage_dir, filename)
        self.total_coverage.merge_sancov_file(sancov_path)
    else:
      os.makedirs(self.coverage_dir)

  def check_distilled_directory(self):
    self.distilled_dir = self.args.distilled
    if not os.path.isdir(self.distilled_dir):
      raise AccdFailedException('Directory ' + self.distilled_dir + ' does not exist')
    self.total_coverage = Coverage()
    self.read_existing_coverage()

  def main(self):
    self.args = self.parse_args()
    if not self.args.command:
      self.parser.print_help()
      return 1
    self.import_sancov()
    self.check_distilled_directory()
    pprint.pprint(vars(self.total_coverage))

if __name__ == '__main__':
  accd = Accd()
  sys.exit(accd.main())
