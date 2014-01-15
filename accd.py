#!/usr/bin/env python

import argparse
import array
import copy
import imp
import os
import re
import psutil
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

  def merge(self, other):
    got_new_coverage = not other.offsets <= self.offsets
    self.offsets |= other.offsets
    return got_new_coverage

  def save(self, directory):
    sancov_path = os.path.join(directory, self.module + '.sancov')
    self.write_sancov(sancov_path)

  def read_sancov(self, sancov_path):
    f = open(sancov_path, mode="rb")
    size = os.fstat(f.fileno()).st_size
    self.offsets = set(array.array('I', f.read(size)))
    f.close()

  def write_sancov(self, sancov_path):
    f = open(sancov_path, mode="w+b")
    array.array('I', self.offsets).tofile(f)
    f.close()

class Coverage:
  def __init__(self, directory='', sancov_regex=''):
    self.modules = {}
    if directory:
      regex = re.compile(sancov_regex)
      for filename in os.listdir(directory):
        if regex.match(filename):
          sancov_path = os.path.join(directory, filename)
          self.merge_sancov_file(sancov_path)
      
  def merge_sancov_file(self, sancov_path):
    module = ModuleCoverage(sancov_path)
    return self.merge_module(module)

  def merge_module(self, module):
    module_name = module.module
    if module_name in self.modules:
      return self.modules[module_name].merge(module)
    else:
      self.modules[module_name] = copy.deepcopy(module)
      return len(module.offsets) != 0

  def merge(self, other):
    got_new_coverage = False
    for module in other.modules.values():
      got_new_coverage |= self.merge_module(module)
    return got_new_coverage

  def save(self, directory):
    for module in self.modules.values():
      module.save(directory)

class Accd:
  def parse_args(self):
    description        =  'Coverage tool based on ASAN coverage.'
    corpus_dir_help    = ('Directory where to store the distilled corpus. '
                          'If it already exists, newly distilled testcases will be added.')
    testcases_dir_help =  'Input directory for undistilled testcases.'
    command_help       = ('The rest of the command line will be executed as a command that '
                          'processes a testcase. Testcase name can be referenced by %%testcase.')
    timeout_help       =  'Timeout in seconds for the command will be killed.'
    sancov_regex_help = ('Regular expression that selects which of the generated .sancov files '
                          'should be used for coverage. %%pid matches the pid of command process. '
                          '%%pid is useful if the command executes child processes, whose .sancov '
                          'files should be ignored.')
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('corpus_dir', help=corpus_dir_help)
    parser.add_argument('testcases_dir', help=testcases_dir_help)
    parser.add_argument('command', help=command_help, nargs=argparse.REMAINDER)
    parser.add_argument('--timeout', dest='timeout', default=None, help=timeout_help)
    parser.add_argument('--sancov-regex', dest='sancov_regex', default='', help=sancov_regex_help)
    self.parser = parser
    return parser.parse_args()

  def read_total_coverage(self):
    self.corpus_dir = self.args.corpus_dir
    self.coverage_dir = os.path.join(self.corpus_dir, 'coverage')
    if not os.path.isdir(self.corpus_dir):
      os.mkdir(self.corpus_dir)
    if os.path.isdir(self.coverage_dir):
      self.total_coverage = Coverage(self.coverage_dir)
    else:
      self.total_coverage = Coverage()

  def get_testcase_coverage(self, testcase_path):
    command = [arg.replace('%%testcase', testcase_path) for arg in self.args.command]
    work_dir = tempfile.mkdtemp()
    devnull = open(os.devnull, "rwb")
    process = psutil.Popen(command, stdin=devnull, stdout=devnull, stderr=devnull, cwd=work_dir);
    testcase_coverage = None
    try:
      pid = process.pid
      process.wait(self.args.timeout)
      sancov_regex = self.args.sancov_regex.replace('%%pid', str(pid))
      testcase_coverage = Coverage(work_dir, sancov_regex)
    except psutil.TimeoutExpired:
      process.kill()
    shutil.rmtree(work_dir)
    return testcase_coverage

  def process_testcase(self, testcase_path):
    testcase_coverage = self.get_testcase_coverage(testcase_path)
    if self.total_coverage.merge(testcase_coverage):
      testcase_save_path = os.path.join(self.corpus_dir, filename)
      shutil.copyfile(testcase_path, testcase_save_path)

  def process_testcases(self):
    testcases_dir = self.args.testcases_dir
    if not os.path.isdir(testcases_dir):
      raise AccdFailedException('Directory ' + testcases_dir + ' does not exist.')
    for filename in os.listdir(testcases_dir):
      self.process_testcase(os.path.join(testcases_dir, filename))

  def save_total_coverage(self):
    if os.path.isdir(self.coverage_dir):
      shutil.rmtree(self.coverage_dir)
    os.mkdir(self.coverage_dir)
    self.total_coverage.save(self.coverage_dir)

  def main(self):
    self.args = self.parse_args()
    if not self.args.command:
      self.parser.print_help()
      return 1
    self.read_total_coverage()
    self.process_testcases()
    self.save_total_coverage()
    return 0

if __name__ == '__main__':
  accd = Accd()
  sys.exit(accd.main())
