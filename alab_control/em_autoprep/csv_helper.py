import csv
import os
CWD = os.getcwd()
positions = {}

def float_or_none(s):
  if s == 'None':
    return None
  return float(s)

#TODO: Move this function to sample_prep.py
def read_CSV_into_positions(path): 
  with open(path, mode ='r') as file:
    csvFile = csv.reader(file)
    for lines in csvFile:
      #Each line has a list of 4 arguments, argument 0 is the name of the position, and argument 1, 2, 3 correspond to x, y, z, respectively
      positions[lines[0]] = ((float_or_none(lines[1]), float_or_none(lines[2]), float_or_none(lines[3])))
  return positions


