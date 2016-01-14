#!/usr/bin/env python

import sys, os, re, ast
import datetime
import json
import hashlib
import sqlite3
import fnmatch
import copy
from collections import defaultdict
from zippylib import flatten
from zippylib.primer import Primer, Locus, PrimerPair

class PrimerDB(object):
    def __init__(self, database, user='unkown'):
        # open database and get a cursor
        self.sqlite = database
        self.db = sqlite3.connect(self.sqlite)
        self.user = user
        # create file table if not exists
        cursor = self.db.cursor()
        try:
            # TABLE
            cursor.execute('CREATE TABLE IF NOT EXISTS primer(name TEXT PRIMARY KEY, seq TEXT, tm REAL, gc REAL, FOREIGN KEY(seq) REFERENCES target(seq));')
            cursor.execute('CREATE TABLE IF NOT EXISTS target(seq TEXT, chrom TEXT, position INT, reverse BOOLEAN, FOREIGN KEY(seq) REFERENCES primer(seq));')
            cursor.execute('CREATE TABLE IF NOT EXISTS pairs(pairid TEXT, uniqueid TEXT, left TEXT, right TEXT, chrom TEXT, start INT, end INT, FOREIGN KEY(left) REFERENCES primer(seq), FOREIGN KEY(right) REFERENCES primer(seq), UNIQUE (pairid, uniqueid) ON CONFLICT REPLACE);')
            cursor.execute('CREATE TABLE IF NOT EXISTS status(pairid TEXT NOT NULL REFERENCES pairs(pairid), uniqueid TEXT NOT NULL REFERENCES pairs(uniqueid), status INT, dateadded TEXT, UNIQUE (pairid, uniqueid) ON CONFLICT REPLACE);')
            cursor.execute('CREATE INDEX IF NOT EXISTS seq_index_in_target ON target(seq);')
            self.db.commit()
        except:
            print >> sys.stderr, self.sqlite
            print >> sys.stderr, self.db
            print >> sys.stderr, cursor
            raise
        finally:
            self.db.close()
        return

    def __str__(self):
        return '<ZippyDB at %s>' % self.sqlite

    def __repr__(self):
        try:
            self.db = sqlite3.connect(self.sqlite)
        except:
            raise
        else:
            cursor = self.db.cursor()
            cursor.execute('''SELECT DISTINCT
                p.pairid, p.uniqueid, p.left, p.right, p.chrom, p.start, p.end, s.status, s.dateadded
                FROM pairs as p, status as s
                WHERE p.pairid = s.pairid AND p.uniqueid = s.uniqueid;''')
            rows = cursor.fetchall()
        finally:
            self.db.close()
        return "\n".join([ '{:<20} {:40} {:<25} {:<25} {:<8} {:>9d} {:>9d} {:1} {}'.format(*row) for row in rows ])

    '''show/update blacklist'''
    def blacklist(self,add=None):
        try:
            self.db = sqlite3.connect(self.sqlite)
        except:
            raise
        else:
            if add:
                cursor.execute('''UPDATE OR ABORT status as s SET s.status = 0 WHERE pairid = ?)''', (add))
                self.db.commit()
                return  # does this close the connection?
            else:
                cursor = self.db.cursor()
                cursor.execute('''SELECT DISTINCT
                    p.pairid, p.uniqueid, p.left, p.right, p.chrom, p.start, p.end, s.status, s.dateadded
                    FROM pairs as p, status as s
                    WHERE p.pairid = s.pairid AND p.uniqueid = s.uniqueid
                    AND s.status = 0;''')
                rows = cursor.fetchall()
                return "\n".join([ '{:<16} {:40} {:<25} {:<25} {:<8} {:>9d} {:>9d} {:1} {}'.format(*row) for row in rows ])
        finally:
            self.db.close()

    '''adds list of primers to database'''
    def addPrimer(self, *primers):
        try:
            self.db = sqlite3.connect(self.sqlite)
        except:
            raise
        else:
            for p in primers:
                cursor = self.db.cursor()
                cursor.execute('''INSERT OR REPLACE INTO primer(name,seq,tm,gc) VALUES(?,?,?,?)''', \
                    (p.name, p.seq, p.tm, p.gc))
                for l in p.loci:
                    cursor.execute('''INSERT OR REPLACE INTO target(seq,chrom,position,reverse) VALUES(?,?,?,?)''', \
                        (p.seq, l.chrom, l.offset, l.reverse))
            self.db.commit()
        finally:
            self.db.close()
        return

    def addPair(self, *pairs):
        '''adds primer pairs (and individual primers)'''
        # add primers
        flat = []
        for p in pairs:
            flat.append(p[0])
            flat.append(p[1])
        self.addPrimer(*flat)
        # add pairs
        try:
            self.db = sqlite3.connect(self.sqlite)
        except:
            raise
        else:
            cursor = self.db.cursor()
            # add pairs
            for p in pairs:
                left, right = p[0],p[1]
                # find common substring in name for automatic naming
                chrom = left.targetposition.chrom
                start = left.targetposition.offset
                end = right.targetposition.offset+right.targetposition.length
                cursor.execute('''INSERT OR REPLACE INTO pairs(pairid,uniqueid,left,right,chrom,start,end) VALUES(?,?,?,?,?,?,?)''', \
                    (p.name(), p.uniqueid(), left.seq, right.seq, chrom, start, end))
                cursor.execute('''INSERT OR REPLACE INTO status(pairID,uniqueid,dateadded) VALUES(?,?,?)''', \
                    (p.name(), p.uniqueid(), datetime.datetime.now()))
            self.db.commit()
        finally:
            self.db.close()
        return

    def query(self, variant):
        '''returns suitable primer pairs for the specified interval'''
        try:
            self.db = sqlite3.connect(self.sqlite)
        except:
            raise
        else:
            cursor = self.db.cursor()
            cursor.execute('''SELECT DISTINCT p.pairid, p.left, p.right, p.chrom, p.start, p.end, s.status,
                abs(p.start+((p.end-p.start)/2) - ?) as midpointdistance
                FROM pairs AS p, status AS s
                WHERE p.pairid = s.pairid AND p.uniqueid = s.uniqueid
                AND p.chrom = ?
                AND p.start + length(p.left) <= ?
                AND p.end - length(p.right) >= ?
                ORDER BY midpointdistance;''', \
                (variant.chromStart+int(variant.chromEnd-variant.chromStart)/2.0, variant.chrom, variant.chromStart, variant.chromEnd))
            rows = cursor.fetchall()
        finally:
            self.db.close()
        # return primer pairs that would match
        primerPairs = []
        for row in rows:
            name = row[0]
            leftSeq = row[1]
            rightSeq = row[2]
            leftTargetposition = Locus(row[3], row[4], len(row[1]), False)
            rightTargetposition = Locus(row[3], row[5]-len(row[2]), len(row[2]), True)
            leftPrimer = Primer(name+'_left', leftSeq, leftTargetposition)
            rightPrimer = Primer(name+'_right', rightSeq, rightTargetposition)
            leftPrimer.calcProperties()
            rightPrimer.calcProperties()
            primerPairs.append(PrimerPair([leftPrimer, rightPrimer], status=row[6]))
        return primerPairs  # ordered by midpoint distance

    def dump(self,what,**kwargs):
        raise NotImplementedError
        if what=='amplicons':
            # dump amplicons (all possible)
            try:
                self.db = sqlite3.connect(self.sqlite)
            except:
                raise
            else:
                cursor = self.db.cursor()
                # FWD strand
                cursor.execute('''SELECT DISTINCT t1.chrom, t1.pos, t2.pos+length(t2.seq), p.pairid
                    FROM pairs AS p
                    LEFT JOIN target AS t1 ON p.left = t1.seq
                    LEFT JOIN target AS t2 ON p.right = t2.seq
                    WHERE t1.chrom = t2.chrom
                    AND t2.pos+length(t2.seq)-t1.pos >= ?
                    AND t2.pos+length(t2.seq)-t1.pos <= ?
                    AND t1.reverse = 0
                    AND t2.reverse = 1
                    ORDER BY t1.chrom, t1.pos;''', (kwargs['size'][0],kwargs['size'][1]))
                rows = cursor.fetchall()
                # REV strand
                cursor.execute('''SELECT DISTINCT t1.chrom, t1.pos, t2.pos+length(t2.seq), p.pairid
                    FROM pairs AS p
                    LEFT JOIN target AS t1 ON p.right = t1.seq
                    LEFT JOIN target AS t2 ON p.left = t2.seq
                    WHERE t1.chrom = t2.chrom
                    AND t2.pos+length(t2.seq)-t1.pos >= ?
                    AND t2.pos+length(t2.seq)-t1.pos <= ?
                    AND t1.reverse = 0
                    AND t2.reverse = 1
                    ORDER BY t1.chrom, t1.pos;''', (kwargs['size'][0],kwargs['size'][1]))
                rows += cursor.fetchall()
            finally:
                self.db.close()
            return rows, ('chrom','chromStart','chromEnd','name')  # rows and colnames
            # return [ '{}\t{}\t{}\t{}'.format(*row) for row in rows ]

'''
def update(self,filename,bucket='default'):
        # parse filenames
        if type(filename) is not list and type(filename) is not tuple:
            inserts = [ (filename, bucket, datetime.datetime.now()) ]
        else:
            inserts = [ (fn, bucket, datetime.datetime.now()) for fn in filename ]
        # execute query
        self.db = sqlite3.connect(self.sqlite)
        cursor = self.db.cursor()
        try:
            cursor.executemany('INSERT OR REPLACE INTO files(filename,bucket,created) VALUES(?,?,?)', inserts)
            self.db.commit()
        except:
            print >> sys.stderr, filename
            print >> sys.stderr, bucket
            print >> sys.stderr, datetime.date.today()
            raise
        finally:
            self.db.close()
        return
'''