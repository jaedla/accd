#!/usr/bin/env python

import argparse

if __name__ == '__main__':
  desc             = 'Coverage tool based on ASAN coverage.'
  distilled_help   = ('Directory where to store the distilled corpus. '
                      'If it already exists, newly distilled testcases will be added.')
  undistilled_help = 'Input directory for undistilled testcases.'
  parser = argparse.ArgumentParser(description=desc)
  parser.add_argument('distilled', help=distilled_help)
  parser.add_argument('undistilled', help=undistilled_help)
  parsed = parser.parse_args();
  print sys.argv[-2], sys.argv[-1]
