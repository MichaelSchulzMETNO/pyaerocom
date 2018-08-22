################################################################
# read_aeronet_invv2.py
#
# read Aeronet inversion V2 data
#
# this file is part of the pyaerocom package
#
#################################################################
# Created 20180629 by Jan Griesfeller for Met Norway
#
# Last changed: See git log
#################################################################

# Copyright (C) 2018 met.no
# Contact information:
# Norwegian Meteorological Institute
# Box 43 Blindern
# 0313 OSLO
# NORWAY
# E-mail: jan.griesfeller@met.no
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301, USA

import os
from copy import deepcopy
import numpy as np
import pandas as pd
from pyaerocom import const
from pyaerocom.io.readungriddedbase import ReadUngriddedBase
from pyaerocom import StationData
from pyaerocom.io.ebas_varinfo import EbasVarInfo
from pyaerocom.io.ebas_file_index import EbasFileIndex
from pyaerocom.io import EbasNasaAmesFile
from pyaerocom.exceptions import VariableDefinitionError, NotInFileError

class ReadEbas(ReadUngriddedBase):
    """Interface for reading EBAS data

    Parameters
    ----------
    dataset_to_read
        string specifying either of the supported datasets that are defined 
        in ``SUPPORTED_DATASETS``
        
    TODO
    ----
    Check for negative values vs. detection limit
    """
    
    #: version log of this class (for caching)
    __version__ = "0.02_" + ReadUngriddedBase.__baseversion__
    
    #: preferred order of data statistics. Some files may contain multiple 
    #: columns for one variable, where each column corresponds to one of the
    #: here defined statistics that where applied to the data. This attribute
    #: is only considered for ebas variables, that have not explicitely defined
    #: what statistics to use (and in which preferred order, if appicable).
    #: Reading preferences for all Ebas variables are specified in the file
    #: ebas_config.ini in the data directory of pyaerocom
    PREFER_STATISTICS = ['arithmetic mean',
                         'percentile:15.87',
                         'percentile:84.13']
    
    #: Wavelength tolerance in nm for reading of variables. If multiple matches
    #: occure, the closest wavelength to the desired wavelength is chosen
    #: e.g. if 50 and for variable at 550nm, accept everything in interval
    #: {500, 600}
    WAVELENGTH_TOL_NM = 50
    
    #: Name of dataset (OBS_ID)
    DATASET_NAME = const.EBAS_MULTICOLUMN_NAME
    
    
    #: List of all datasets supported by this interface
    SUPPORTED_DATASETS = [const.EBAS_MULTICOLUMN_NAME]
    
    TS_TYPE = 'undefined'
    
    # TODO: check and redefine 
    #: default variables for read method
    DEFAULT_VARS = ['absc550aer', # light absorption coefficient
                    'scatc550aer'] # light scattering coefficient
    
    # Temporal resolution codes that (so far) can be understood by pyaerocom
    TS_TYPE_CODES = {'1h'   :   'hourly',
                     '1d'   :   'daily',
                     '1mo'  :   'monthly'}
    
    # list of all available resolution codes (extracted from SQL database)
    # 1d 1h 1mo 1w 4w 30mn 2w 3mo 2d 3d 4d 12h 10mn 2h 5mn 6d 3h 15mn
    
    #: List of variables that are provided by this dataset (will be extended 
    #: by auxiliary variables on class init, for details see __init__ method of
    #: base class ReadUngriddedBase)
    def __init__(self, dataset_to_read=None):
        super(ReadEbas, self).__init__(dataset_to_read)
        #: loaded instances of aerocom variables (instances of 
        #: :class:`Variable` object, is written in get_file_list
        self.loaded_aerocom_vars = {}
        
        #: original file lists retrieved for each variable individually using
        #: SQL request. Since some of the files in the lists for each variable
        #: might occur in multiple lists, these are merged into a single list 
        #: self.files and information about which variables are to be extracted 
        #: for each file is stored in attribute files_contain
        
        #: Originally retrieved file lists from SQL database, for each variable
        #: individually
        self._lists_orig = {}
        
        #: this is filled in method get_file_list and specifies variables 
        #: to be read from each file
        self.files_contain = []
        
        #: Interface to access aerocom variable information (instance of class
        #: AllVariables)
        self.aerocom_vars = const.VAR_PARAM
        
        #: EBAS I/O variable information
        self._ebas_vars = EbasVarInfo.PROVIDES_VARIABLES()
        
        #: SQL database interface class used to retrieve file paths for vars
        self.file_index = EbasFileIndex()
        
    @property
    def _FILEMASK(self):
        raise AttributeError("Irrelevant for EBAS implementation, since SQL "
                             "database is used for finding valid files")
    @property
    def NAN_VAL(self):
        """Irrelevant for implementation of EBAS I/O"""
        raise AttributeError("Irrelevant for EBAS implementation: Info about "
                             "invalid measurements is extracted from header of "
                             "NASA Ames files for each variable individually ")
    @property
    def PROVIDES_VARIABLES(self):
        """List of variables provided by the interface"""
        return self._ebas_vars

    def _merge_lists(self, lists_per_var):
        """Merge dictionary of lists for each variable into one list
        
        Note
        ----
        In addition to writing the retrieved file list into :attr:`files`, this 
        method also fills the list :attr:`files_contain` which (by index)
        defines variables to read for each file path in :attr:`files`
        
        Parameters
        ----------
        lists_per_var : dict
            dictionary containing file lists (values) for a set of variables
            (keys)
        
        Returns
        -------
        list
            merged file list (is also written into :attr:`files`)
        """
        # original lists are modified, so make a copy of them
        lists = deepcopy(lists_per_var)
        mapping = {}
        for var, lst in lists.items():
            for fpath in lst:
                if fpath in mapping:
                    raise Exception('FATAL: logical error -> this should not occur...')
                mapping[fpath] = [var]
                for other_var, other_lst in lists.items():
                    if not var == other_var:
                        try:
                            other_lst.pop(other_lst.index(fpath))
                            mapping[fpath].append(other_var)
                        except ValueError:
                            pass
        self.logger.info('Number of files to read reduced to {}'.format(len(mapping)))
        files, files_contain = [], []
        for path, contains_vars in mapping.items():
            files.append(path)
            files_contain.append(contains_vars)
        self.files = files
        self.files_contain = files_contain
        return files
    
    def get_file_list(self, vars_to_retrieve=None):
        """Get list of files for all variables to retrieve
        
        Note
        ----
        Other than in other implementations of the base class, this 
        implementation returns a dictionary containing file lists for each 
        of the specified variables. This is because in EBAS, some of the 
        variables require additional specifications to the variable name, such
        as the EBAS matrix or the instrument used. For instance, the EBAS
        variable *sulphate_total* specifies either sulfate concentrations in
        precipitable water (EBAS matrix: precip) or in air (e.g. matrix aerosol,
        pm1, pm10 ...)
        
        Todo
        ----
        After searching file list for each variable, find common files for all
        variables and make one list ``common`` that can then be used to avoid 
        that several files are read multiple times.
        
        Parameters
        ----------
        vars_to_retrieve : list
            list of variables that are supposed to be loaded
            
        Returns
        -------
        list 
            unified list of file paths each containing either of the specified 
            variables
        """
        if vars_to_retrieve is None:
            vars_to_retrieve = self.DEFAULT_VARS
        elif isinstance(vars_to_retrieve, str):
            vars_to_retrieve = [vars_to_retrieve]
            
        self.logger.info('Fetching data files. This might take a while...')
        
        db = self.file_index
        files_vars = {}
        totnum = 0
        for var in vars_to_retrieve:
            if not var in self.PROVIDES_VARIABLES:
                raise AttributeError('No such variable {}'.format(var))
            info = EbasVarInfo(var)
            if info.requires is not None:
                raise NotImplementedError('Auxiliary variables can not yet '
                                          'be handled / retrieved')
            try:
                filenames = db.get_file_names(info.make_sql_request())
            except Exception as e:
                self.logger.warning('Failed to retrieve files for variable '
                                    '{}. Error: {}'.format(var, repr(e)))
            paths = []
            for file in filenames:
                paths.append(os.path.join(const.EBASMC_DATA_DIR, file))
            files_vars[var] = sorted(paths)
            num = len(paths)
            totnum += num
            self.logger.info('{} files found for variable {}'.format(num, var))
        if len(files_vars) == 0:
            raise IOError('No file could be retrieved for either of the '
                          'specified input variables: {}'.format(vars_to_retrieve))
        
        self._lists_orig = files_vars
        files = self._merge_lists(files_vars)
        return files
    
    def _get_var_cols(self, varname_ebas, data):
        """Get all columns in NASA Ames file matching input Aerocom variable
        
        Note
        ----
        For developers: All Aerocom variable definitions should go into file
        *variables.ini* in pyaerocom data directory.
        
        Parameters
        -----------
        var : str
            EBAS variable name (e.g. absc550aer)
        data : EbasNasaAmesFile
            loaded EBAS file data
        
        Returns
        -------
        dict
            key value pairs specifying all matches of input variable, where 
            keys are the column index and values are instances of
            :class:`EbasColDef` specifying further information such as unit, 
            or sampling wavelength.
        
        Raises
        ------
        VariableDefinitionError
            if inconsistencies occur or variable is not unembiguously defined
            (e.g. EBAS column variable contains wavelength information but 
            wavelength of Aerocom variable)
        """
        
        col_info = {}
        for i, info in enumerate(data.var_defs):
            if varname_ebas == info.name:
                col_info[i] = info
        if len(col_info) is 0:
            raise NotInFileError("Variable {} could not be found in file".format(varname_ebas))
        return col_info
        
        
    def read_file(self, filename, vars_to_retrieve=None,
                  vars_as_series=False):
        """Read Aeronet file containing results from v2 inversion algorithm

        Parameters
        ----------
        filename : str
            absolute path to filename to read
        vars_to_retrieve : list
            list of str with variable names to read
        vars_as_series : bool
            if True, the data columns of all variables in the result dictionary
            are converted into pandas Series objects
            
        Returns
        -------
        StationData
            dict-like object containing results
        """
        # implemented in base class
        vars_to_read, vars_to_compute = self.check_vars_to_retrieve(vars_to_retrieve)
       
        file = EbasNasaAmesFile(filename)

        var_cols = {}
        all_vars = self.aerocom_vars
        for var in vars_to_read:
            if not var in self.loaded_aerocom_vars:
                self.loaded_aerocom_vars[var] = all_vars[var]
            var_info = self.loaded_aerocom_vars[var]
            var_info_ebas = EbasVarInfo(var)
            
            matches = {}
            # this variable may go under multiple names in EBAS
            # (e.g. SCONC_SO4 -> sulphate_corrected, sulphate_total)
            for varname_ebas in var_info_ebas.component:
                try:
                    # all columns in file that match the EBAS variable name
                    # (may be multiple)
                    col_matches = self._get_var_cols(varname_ebas, file)
                except NotInFileError:
                    continue
                # init helper variable for finding closest wavelength (if 
                # no exact wavelength match can be found)
                min_diff_wvl = 1e6
                for colnum, colinfo in col_matches.items():
                    if 'wavelength' in colinfo:
                        wvl = var_info.wavelength_nm
                        if wvl is None:
                            raise VariableDefinitionError('Require wavelength '
                                'specification for Aerocom variable {}'.format(var))
                        wvl_col = colinfo.get_wavelength_nm()
                        wvl_low = wvl - self.WAVELENGTH_TOL_NM
                        wvl_high = wvl + self.WAVELENGTH_TOL_NM
                        # wavelength is in tolerance range
                        if wvl_low <= wvl_col <= wvl_high:
                            wvl_diff = abs(wvl_col - wvl)
                            if wvl_diff < min_diff_wvl:
                                # the wavelength difference of this column to
                                # the desired wavelength of the variable is 
                                # smaller than any of the detected before, so
                                # ignore those from earlier columns by reinit
                                # of the matches dictionary
                                min_diff_wvl = wvl_diff
                                matches = {}
                            matches[colnum] = colinfo
                    
                    elif 'location' in colinfo:
                        raise NotImplementedError('For developers, please '
                                                  'check!')
                    else:
                        matches[colnum] = colinfo
            if matches:
                # loop was interrupted since exact wavelength match was found
                var_cols[var] = matches
        
        if not len(var_cols) > 0:
            raise NotInFileError('None of the specified variables {} could be '
                                 'found in file {}'.format(vars_to_read,
                                                os.path.basename(filename)))
        
    
        #create empty data object (is dictionary with extended functionality)
        data_out = StationData()
        data_out.dataset_name = self.DATASET_NAME
        
        
        meta = file.meta
        # write meta information
        tres_code = meta['resolution_code']
        try:
            ts_type = self.TS_TYPE_CODES[tres_code]
        except KeyError:
            self.logger.info('Unkown temporal resolution {}'.format(tres_code))
            ts_type = 'undefined'
        data_out['ts_type'] = ts_type
        # altitude of station
        stat_alt = float(meta['station_altitude'].split(' ')[0])
        try:
            meas_height = float(meta['measurement_height'].split(' ')[0])
        except KeyError:
            meas_height = 0.0
        data_alt = stat_alt + meas_height
            
        
        data_out['stat_lon'] = float(meta['station_latitude'])
        data_out['stat_lat'] = float(meta['station_longitude'])
        data_out['stat_alt'] = stat_alt
        data_out['station_name'] = meta['station_name']
        data_out['PI'] = meta['submitter']
        data_out['altitude'] = data_alt
        
        # store the raw EBAS meta dictionary (who knows what for later ;P )
        data_out['ebas_meta'] = meta
        
        dtime = file.time_stamps
        num_times = len(dtime)
        data_out['var_info'] = {}
        for var, info  in var_cols.items():
            num_matches = len(info)
            data = np.empty((num_matches, num_times))
            var_info = []
            for i, colnum in enumerate(info.keys()):
                data[i] = file.data[:, colnum]
                var_info.append(info[colnum])
            data_out[var] = data
            data_out['var_info'][var] = var_info
                    
        data_out['dtime'] = dtime
        # compute additional variables (if applicable)
        data_out = self.compute_additional_vars(data_out, vars_to_compute)
        
        if vars_as_series:        
            for var in (vars_to_read + vars_to_compute):
                if var in vars_to_retrieve:
                    data_out[var] = pd.Series(data_out[var], 
                                              index=data_out['dtime'])
                else:
                    del data_out[var]
            
        return data_out
    
    def read(self):
        raise NotImplementedError
        
if __name__=="__main__":
    from pyaerocom import change_verbosity
    change_verbosity('critical')

    read = ReadEbas()
    
    files = read.get_file_list()
        
    FILE = 0
    test_file = read.files[FILE]
    test_file_contains = read.files_contain[FILE]
    d0 = EbasNasaAmesFile(test_file)
    
    data = read.read_file(test_file, vars_to_retrieve=test_file_contains)
    print(data)
    
    DO_META_TEST = False
    DO_TIME_SAMPLE_TEST = False
    if DO_TIME_SAMPLE_TEST:
        files_failed = []
        has_24h = []
        success = 0
        failed = 0
        file_info = {}
        for file in files[:200]:
            try:
                data = read.read_file(file)
                days_vs_num = {}
                prev_date= 0 
                for t in data.dtime:
                    date = t.astype('datetime64[D]')
                    if not date == prev_date:
                        if prev_date != 0:
                            if days_vs_num[prev_date] == 24:
                                has_24h.append(True)
                            else:
                                has_24h.append(False)
                                
                        days_vs_num[date] = 1
                    else:
                        days_vs_num[date] += 1
                    prev_date = date
                file_info[file] = days_vs_num
                success += 1
            except NotInFileError:
                failed += 1
                files_failed.append(file)
        for file in files_failed:
            data = EbasNasaAmesFile(file, only_head=True)
            print("File {} contains:\n".format(file))
            for var in data.var_defs:
                if var.is_var:
                    print(repr(var))
            print()
            print()

                
    if DO_META_TEST:
        totnum = len(files)
        failed = 0
        mat_in_head = 0
        mat_in_coldef =  0
        mat_in_both = 0
        mat_in_none = 0
        stat_in_head = 0
        stat_in_coldef = 0
        stat_in_both = 0
        stat_in_none = 0
        for i, f in enumerate(read.files):
            if i%25 == 0:
                print('File {} of {}'.format(i, totnum))
            _mat_in_head = 0
            _mat_in_coldef =  0
            _mat_in_both = 0
            _stat_in_head = 0
            _stat_in_coldef = 0
            _stat_in_both = 0
            try:
                head = EbasNasaAmesFile(f, only_head=True)
                for col in head.var_defs:
                    if 'matrix' in col:
                        _mat_in_coldef = 1
                    if 'statistics' in col:
                        _stat_in_coldef = 1
                if 'matrix' in head.meta:
                    _mat_in_head = 1
                if 'statistics' in head.meta:
                    _stat_in_head = 1
                if _mat_in_coldef and _mat_in_head:
                    _mat_in_both = True
                if _stat_in_coldef and _stat_in_head:
                    _stat_in_both = True
                if not _mat_in_coldef and not _mat_in_head:
                    mat_in_none += 1
                if not _stat_in_coldef and not _stat_in_head:
                    stat_in_none += 1
                mat_in_both += _mat_in_both
                mat_in_coldef += _mat_in_coldef
                mat_in_head += _mat_in_head
                
                stat_in_both += _stat_in_both
                stat_in_coldef += _stat_in_coldef
                stat_in_head += _stat_in_head
                   
            except:
                failed += 1