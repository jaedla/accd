#!/usr/bin/env python

import argparse
import array
import copy
import imp
import os
import re
import shutil
import subprocess
import sys
import tempfile

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
    self.read_sancov(sancov_path)

  def read_sancov(self, sancov_path):
    f = open(sancov_path, mode="rb")
    size = os.fstat(f.fileno()).st_size
    self.offsets = set(array.array('I', f.read(size)))
    f.close()

  def merge(self, other):
    self.offsets |= other.offsets

class Coverage:
  def __init__(self, directory='', filename_regex=''):
    self.modules = {}
    if directory:
      regex = re.compile(filename_regex)
      for filename in os.listdir(directory):
        if regex.match(filename):
          sancov_path = os.path.join(directory, filename)
          self.merge_sancov_file(sancov_path)
      
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
    testcases_help   =  'Input directory for undistilled testcases.'
    command_help     = ('The rest of the command line will be executed as a command that '
                        'processes a testcase. Testcase name can be referenced by %%testcase')
    timeout_help     =  'Timeout in seconds, when the command will be killed'
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('distilled', help=distilled_help)
    parser.add_argument('testcases', help=testcases_help)
    parser.add_argument('command', help=command_help, nargs=argparse.REMAINDER)
    parser.add_argument('--timeout', dest='timeout', help=timeout_help)
    self.parser = parser
    return parser.parse_args()

  def read_existing_coverage(self):
    self.coverage_dir = os.path.join(self.distilled_dir, 'coverage')
    if os.path.isdir(self.coverage_dir):
      self.total_coverage = Coverage(self.coverage_dir)
    else:
      self.total_coverage = Coverage()
      os.makedirs(self.coverage_dir)

  def check_distilled_directory(self):
    self.distilled_dir = self.args.distilled
    if not os.path.isdir(self.distilled_dir):
      raise AccdFailedException('Directory ' + self.distilled_dir + ' does not exist.')
    self.read_existing_coverage()

  def process_testcase(self, testcase_path):
    command = [arg.replace('%%testcase', testcase_path) for arg in self.args.command]
    cwd = os.getcwd()
    work_dir = tempfile.mkdtemp()
    
    shutil.rmtree(work_dir)

  def process_testcases(self):
    testcases_dir = self.args.testcases
    if not os.path.isdir(testcases_dir):
      raise AccdFailedException('Directory ' + testcases_dir + ' does not exist.')
    for filename in os.listdir(testcases_dir):
      testcase_path = os.path.join(testcases_dir, filename)
      self.process_testcase(testcase_path)

  def main(self):
    self.args = self.parse_args()
    if not self.args.command:
      self.parser.print_help()
      return 1
    self.check_distilled_directory()
    self.process_testcases()

if __name__ == '__main__':
  accd = Accd()
  sys.exit(accd.main())
