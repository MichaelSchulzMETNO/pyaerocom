#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from fnmatch import fnmatch
import glob
import os
import numpy as np
import simplejson

# internal pyaerocom imports
from pyaerocom._lowlevel_helpers import (check_dirs_exist, dict_to_str)
from pyaerocom import const
from pyaerocom import __version__ as pyaerocom_version
from pyaerocom.helpers import resample_time_dataarray
from pyaerocom.mathutils import calc_statistics
from pyaerocom.region import (get_all_default_region_ids, 
                              find_closest_region_coord,
                              Region)
from pyaerocom.io.helpers import save_dict_json

from pyaerocom.web.helpers import (ObsConfigEval, ModelConfigEval, 
                                   update_menu, make_info_table)
from pyaerocom import ColocationSetup, ColocatedData, Colocator
from pyaerocom.exceptions import DataDimensionError

# ToDo: complete docstring
class AerocomEvaluation(object):
    """Class for creating json files for Aerocom Evaluation interface
    
    High level interface for computation of colocated netcdf files and json
    files for `Aerocom Evaluation interface 
    <https://aerocom-trends.met.no/evaluation/web/>`__. The processing is 
    done *per experiment*. See class attributes for setup options.
    An *experiment* denotes a setup comprising one or more observation 
    networks (specified in :attr:`obs_config`) and the specification of one 
    or more model runs via :attr:`model_config`. These two configuration 
    attributes are dictionaries, where keys correspond to the name of the
    obs / model (as it should appear online) and values specify relevant 
    information for importing the data (see also classes 
    :class:`ModelConfigEval` and :class:`ObsConfigEval`).
    
    In addition to :attr:`model_config, obs_config`, there are more setup 
    settings and options, some of which NEED to be specified (e.g. 
    :attr:`proj_id, exp_id, out_basedir`) and others that may be explicitly 
    specified if desired (e.g. :attr:`harmonise_units, remove_outliers, 
    clear_existing_json`).
    
    The analysis (which can be run via :func:`run_evaluation`) can be summarised
    as follows: for each combination of *variable / obs / model* create one 
    colocated NetCDF file and based on this colocated (single variable) NetCDF 
    file compute all relevant json files for the interface. 
    
    General settings for the colocation (e.g. colocation frequency, start / 
    stop time) can be specified in :attr:`colocation_settings` (for details 
    see :class:`pyaerocom.ColocationSetup`). The colocation routine uses the 
    variables specified in the obs_config entry of the observation network that 
    is supposed to be colocated. If these variables are not provided in a 
    model run or are named differently, then the corresponding model variable 
    that is supposed to be colocated with the observation variable can be 
    specified in the corresponding model entry in :attr:`model_config` via 
    model_use_vars (mapping). Note that this may lead to unit conversion errors 
    if the mapped model variable has a different AeroCom default unit and if 
    outlier ranges are not specified explicitely (see info below).
    
    If :attr:`remove_outliers` is True, then custom outlier ranges for 
    individual variables may be specified in corresponding entry of model in 
    :attr:`model_config`, or, for observation variables
    in :attr:`obs_config`, respectively. 
    NOTE: for each variable that has not specified an outlier range here, the 
    AeroCom default is used, which is specified in pyaerocom data file 
    variables.ini. In the latter case, a unit check is performed in order to 
    make sure the retrieved default outlier ranges are valid. This can cause 
    errors in the colocation if, for instance, a model variable name is used
    that has a different AerocCom default unit than the used observation 
    variable.
    
    Attributes
    ----------
    proj_id : str
        ID of project
    exp_id : str
        ID of experiment
    exp_name : :obj:`str`, optional
        name of experiment 
    clear_existing_json : bool
        Boolean specifying whether existing json files should be deleted for
        var / obs / model combination before rerunning
    out_basedir : str
        basic output directory which defines all further output paths for json
        files 
    out_dirs : dict
        dictionary that specifies the output paths for the different types of
        json files (e.g. map, ts, etc.). Is filled automatically using 
        :attr:`out_basedir, proj_id, exp_id`. Non existing paths are 
        automatically created.
    colocation_settings : dict
        dictionary specifying settings and options for the colocation routine
        (cf. :class:`pyaerocom.ColocationSetup` for available options). 
        Note: the options that are specified in this dictionary are to be 
        understood as global colocation options (for all model / obs 
        combinations defining this experiment). They may be refined or 
        overwritten as required on an individual basis in the definitions for 
        the observations (:attr:`obs_config`) and / or in the model definitions
        (:attr:`model_config`), respectively. The logical order that defines 
        the colocation settings for a certain run (that is, a combination of 
        `var_name, obs_name, model_name`) is:
        is:
            
            1. Import `dict` :attr:`colocation_settings` (global)
            2. Update `dict` with settings from :attr:`obs_config` for \
            `obs_name` (defines `var_name`)
            3. Update `dict` with settings from :attr:`model_config` for \
            `model_name`
            
    
            
        
    """
    OUT_DIR_NAMES = ['map', 'ts', 'scat', 'hm', 'profiles']
    
    
    #: Vertical layer ranges
    VERT_LAYERS = {'0-2km'  :   [0, 2000],
                   '2-5km'  :   [2000, 5000],
                   '5-10km' :   [5000, 10000]}
    
    #: Allowed options for vertical codes
    VERT_CODES = ['Surface', 'Column']
    VERT_CODES.extend(VERT_LAYERS)
    
    #: Attributes that are ignored when writing setup to json file
    JSON_CFG_IGNORE = ['add_methods', '_log', 'out_dirs']
    
    _OPTS_NAMES_OUTPUT = {
            'clear_existing_json' : 'Delete existing json files before reanalysis',
            'reanalyse_existing'  : 'Reanalyse existing colocated NetCDF files',
            'only_colocation'     : 'Run only colocation (no json files computed)',
            'raise_exceptions'    : 'Raise exceptions if they occur'
    }
                          
    def __init__(self, proj_id=None, exp_id=None, config_dir=None,
                 **settings):
        
        self._log = const.print_log
        
        self.proj_id = proj_id
        
        self.exp_id = exp_id
        
        self.exp_name = None
        
        self.clear_existing_json = True
        self.only_colocation = False
        
        #: Base directory for output
        self.out_basedir = None
        
        #: Directory that contains configuration files
        self.config_dir = config_dir
        
        #: Output directories for different types of json files (will be filled
        #: in :func:`init_dirs`)
        self.out_dirs = {}
        
        #: Dictionary specifying default settings for colocation
        self.colocation_settings = ColocationSetup()
        
        self.add_methods_file = None
        self.add_methods = {}
        
        #: Dictionary containing configurations for observations
        self.obs_config = {}
        self.obs_ignore = []
        
        #: Dictionary containing configurations for models
        self.model_config = {}
        self.model_ignore = []
        
        self.var_mapping = {}
        self.var_order_menu = []
        
        try:
            self.load_config(self.proj_id, self.exp_id, config_dir)
            print('Found and imported config file for {} / {}'.format(self.proj_id,
                  self.exp_id))
        except:
            pass
        self.update(**settings)
        
        self.check_config()
        self.init_dirs()
        self._update_custom_read_methods()
    
    @property
    def proj_dir(self):
        """Project directory"""
        return os.path.join(self.out_basedir, self.proj_id)
    
    @property
    def exp_dir(self):
        """Project directory"""
        return os.path.join(self.proj_dir, self.exp_id)
    
    @property
    def coldata_dir(self):
        """Base directory for colocated data files"""
        return self.colocation_settings['basedir_coldata']
    
    @property
    def regions_file(self):
        """json file containing region specifications"""
        return os.path.join(self.out_basedir, 'regions.json')
    
    @property
    def menu_file(self):
        """json file containing region specifications"""
        return os.path.join(self.proj_dir, 'menu.json')
    
    @property
    def all_model_names(self):
        """List of all model names"""
        return list(self.model_config)
    
    @property
    def all_obs_names(self):
        """List of all obs names"""
        return list(self.obs_config)
    
    @property
    def all_map_files(self):
        """List of all existing map files"""
        return os.listdir(self.out_dirs['map'])
    
    def _update_custom_read_methods(self):
        for mcfg in self.model_config.values():
            if not 'model_read_aux' in mcfg:
                continue
            maux = mcfg['model_read_aux']
            if not isinstance(maux, dict):
                raise ValueError('Require dict, got {}'.format(maux))
            for varcfg in maux.values():
                err_msg_base = ('Invalid definition of model_read_aux')
                if not isinstance(varcfg, dict):
                    raise ValueError('{}: value needs to be dictionary'
                                     .format(err_msg_base))
                if not all([x in varcfg for x in ['vars_required', 'fun']]):
                    raise ValueError('{}: require specification of keys '
                                     'vars_required and fun'
                                     .format(err_msg_base))
                if not isinstance(varcfg['fun'], str):
                    raise ValueError('Names of custom methods need to be strings')
                    
                name = varcfg['fun']
                fun = self.get_custom_read_method_model(name)
                if not name in self.add_methods:
                    self.add_methods[name] = fun
                
                    
    def get_custom_read_method_model(self, method_name):
        """Get custom read method for computation of model variables during read
        
        Parameters
        ----------
        method_name : str
            name of method
            
        Returns
        -------
        callable
            corresponding python method
        
        Raises
        ------
        ValueError
            if no method with the input name can be accessed
        """
        if method_name in self.add_methods:
            fun = self.add_methods[method_name]
        else:
            import sys, importlib
            fp = self.add_methods_file
            
            if fp is None or not os.path.exists(fp):
                raise ValueError('Failed to access custom read method {}'
                                 .format(method_name))
            try:
                moddir = os.path.dirname(fp)
                if not moddir in sys.path:
                    sys.path.append(moddir)
                modname = os.path.basename(fp).split('.')[0]
                if '.' in modname:
                    raise NameError('Invalid name for module: {} (file name must '
                                    'not contain .)'.format(fp))
                mod = importlib.import_module(modname)
            except Exception as e:
                raise ImportError('Failed to import module containing '
                                  'additional custom model read methods '
                                  '.Error: {}'.format(repr(e)))
            if not method_name in mod.FUNS:
                raise ValueError('File {} does not contain custom read '
                                 'method: {}'.format(fp, method_name))
            fun = mod.FUNS[method_name]
        #fun = self.add_methods[name]
        if not callable(fun):
            raise TypeError('{} ({}) is not a callable object'.format(fun, 
                            method_name))
        return fun
        
    def update(self, **settings):
        """Update current setup"""
        for k, v in settings.items():
            self[k] = v
    
    def _set_obsconfig(self, val):
        cfg = {}
        for k, v in val.items():
            cfg[k] = ObsConfigEval(**v)
        self.obs_config = cfg
        
    def _set_modelconfig(self, val):
        cfg = {}
        for k, v in val.items():
            cfg[k] = ModelConfigEval(**v)
        self.model_config = cfg
        self._update_custom_read_methods()
    
            
    def __setitem__(self, key, val):
        if key in self.colocation_settings:
            self.colocation_settings[key] = val
        elif key == 'obs_config':
            self._set_obsconfig(val)
        elif key == 'model_config':
            self._set_modelconfig(val)
        elif key == 'colocation_settings':
            self.colocation_settings.update(**val)
        elif isinstance(key, str) and isinstance(val, dict):
            if 'obs_id' in val:
                if key in self.obs_config:
                    self._log.warn('Obs config for key {}  already exists and '
                                   'will be overwritten {}'.format(key))
                self.obs_config[key] = ObsConfigEval(**val)
            elif 'model_id' in val:
                if key in self.model_config:
                    self._log.warn('Model config for key {}  already exists and '
                                   'will be overwritten {}'.format(key))
                self.model_config[key] = ModelConfigEval(**val)
            else:
                self.__dict__[key] = val
        elif key in self.__dict__:
            self.__dict__[key] = val
        else:
            raise KeyError('Invalid input key {}. Cannot assign {}'
                           .format(key, val))
                
    def __getitem__(self, key):
        if key in self.__dict__:
            return self.__dict__[key]
        elif key in self.colocation_settings:
            return self.colocation_settings[key]
    
    def init_dirs(self, out_basedir=None):
        """Check and create directories"""
        if out_basedir is not None:
            self.out_basedir = out_basedir
        if self.out_basedir is None:
            self.out_basedir = const.OUTPUTDIR
        check_dirs_exist(self.out_basedir, self.proj_dir, self.exp_dir)
        outdirs = {}
        for dname in self.OUT_DIR_NAMES:
            outdirs[dname] = os.path.join(self.exp_dir, dname)
        check_dirs_exist(**outdirs)
        self.out_dirs = outdirs
    
    
    
    def check_config(self):
        if not isinstance(self.proj_id, str):
            raise ValueError('proj_id must be string, got {}'.format(self.proj_id))
        
        if not isinstance(self.exp_id, str):
            raise ValueError('exp_id must be string, got {}'.format(self.exp_id))
            
        if not isinstance(self.exp_name, str):
            const.print_log.warning('exp_name must be string, got {}. Using '
                                    'exp_id {} for experiment name'
                                    .format(self.exp_name, self.exp_id))
            self.exp_name = self.exp_id
        
        for k, v in self.model_config.items():
            if '_' in k or ':' in k:
                raise NameError('Model config name must not contain _ (underscore) or colon.')
            elif len(k) > 20:
                print('Long model ID: {}. Consider renaming'.format(k))
            elif len(k) > 25:
                raise ValueError('Too long model ID: {} (max 20 chars)'.format(k))
            elif not 'model_id' in v:
                raise KeyError('Model configuration for {} does not contain '
                               'model_id'.format(k))
        for k, v in self.obs_config.items():
            if '_' in k or ':' in k:
                raise NameError('Obs config name must not contain _ (underscore) or colon')
            elif len(k) > 15:
                print('Long obs ID: {}. Consider renaming'.format(k))
            elif len(k) > 20:
                raise ValueError('Too long obs ID: {} (max 20 chars)'.format(k))
            elif not 'obs_id' in v:
                raise KeyError('Obs configuration for {} does not contain '
                               'obs_id'.format(k))
                
    def get_model_id(self, model_name):
        """Get AeroCom ID for model name
        """
        for name, info in self.model_config.items():
            if name == model_name:
                return info['model_id']
        raise KeyError('Cannot find setup for ID {}'.format(model_name))
    
    def get_obs_id(self, obs_name):
        """Get AeroCom ID for obs name
        """
        for name, info in self.obs_config.items():
            if name == obs_name:
                return info['obs_id']
        raise KeyError('Cannot find setup for ID {}'.format(obs_name))
    
    def find_obs_name(self, obs_id, obs_var):
        """Find web menu name of obs dataset based on obs_id and variable
        """
        matches = []
        for obs_name, info in self.obs_config.items():
            if info['obs_id'] == obs_id and obs_var in info['obs_vars']:
                matches.append(obs_name)
        if len(matches) == 1:
            return matches[0]
        raise ValueError('Could not identify unique obs name')
    
    def find_model_name(self, model_id):
        """Find web menu name of model dataset based on model_id
        """
        matches = []
        for model_name, info in self.model_config.items():
            if info['model_id'] == model_id:
                matches.append(model_name)
        if len(matches) == 1:
            return matches[0]
        raise ValueError('Could not identify unique model name')
            
    def make_regions_json(self):
        regs = {}
        for regname in get_all_default_region_ids():
            reg = Region(regname)
            regs[regname] = r = {}
            latr = reg.lat_range
            r['minLat'] = latr[0]
            r['maxLat'] = latr[1]
            lonr = reg.lon_range
            r['minLon'] = lonr[0]
            r['maxLon'] = lonr[1]
        save_dict_json(regs, self.REGIONS_FILE)
        return regs
                
    def compute_json_files_from_colocateddata(self, coldata):
        """Creates all json files for one ColocatedData object"""
        if not isinstance(coldata, ColocatedData):
            raise ValueError('Need ColocatedData object, got {}'
                             .format(type(coldata)))
        #d = pya.ColocatedData(file_path)
        d = coldata
        
        stats_dummy = {}
        
        for k in calc_statistics([1], [1]):
            stats_dummy[k] = np.nan
            
        arr = d.data
        if 'altitude' in arr.dims:
            raise NotImplementedError('Cannot yet handle profile data')
        if not 'station_name' in arr.coords:
            if not arr.ndim == 4:
                raise DataDimensionError('Invalid number of dimensions. '
                                         'Need 4, got: {}'
                                         .format(arr.dims))
            elif not 'latitude' in arr.dims and 'longitude' in arr.dims:
                raise DataDimensionError('Need latitude and longitude '
                                         'dimension. Got {}'
                                         .format(arr.dims))
            arr = arr.stack(station_name=('latitude', 'longitude'))
            
        ts_types_order = const.GRID_IO.TS_TYPES
        to_ts_types = ['daily', 'monthly', 'yearly']
        
        data_arrs = dict.fromkeys(to_ts_types)
        jsdate = dict.fromkeys(to_ts_types)
        
        ts_type = d.meta['ts_type']
        for freq in to_ts_types:
            if ts_types_order.index(freq) < ts_types_order.index(ts_type):
                data_arrs[freq] = None
            elif ts_types_order.index(freq) == ts_types_order.index(ts_type):
                data_arrs[freq] = arr
                
                js = (arr.time.values.astype('datetime64[s]') - 
                                   np.datetime64('1970', '[s]')).astype(int) * 1000
                jsdate[freq] = js.tolist()
                
            else:
                data_arrs[freq] = _a = resample_time_dataarray(arr, freq=freq)
                js = (_a.time.values.astype('datetime64[s]') - 
                      np.datetime64('1970', '[s]')).astype(int) * 1000
                jsdate[freq] = js.tolist()      
        
        #print(jsdate)
    
        obs_id = d.meta['data_source'][0]
        model_id = d.meta['data_source'][1]
        
        obs_var = d.meta['var_name'][0]
        model_var = d.meta['var_name'][1]
        
        try:
            obs_name = self.find_obs_name(obs_id, obs_var)
        except:
            obs_name = obs_id
            
        try:
            model_name = self.find_model_name(model_id)
        except:
            model_name = model_id
        ts_objs = []
        
        map_data = []
        scat_data = {}
        hm_data = {}
        
        ts_type = d.meta['ts_type']
        vert_code = self.get_vert_code(obs_name, obs_var)
        
        if vert_code == 'ModelLevel':
            raise NotImplementedError('Coming soon...')
        for i, stat_name in enumerate(arr.station_name.values):
            
            has_data = False
            ts_data = {}
            ts_data['station_name'] = stat_name
            ts_data['pyaerocom_version'] = pyaerocom_version
            ts_data['obs_name'] = obs_name
            ts_data['model_name'] = model_name
            ts_data['obs_var'] = d.meta['var_name'][0]
            ts_data['obs_unit'] = d.meta['unit'][0]
            ts_data['vert_code'] = vert_code
            ts_data['obs_freq_src'] = d.meta['ts_type_src'][0]
            ts_data['obs_revision'] = d.meta['revision_ref']
            
            ts_data['mod_var'] = d.meta['var_name'][1]
            ts_data['mod_unit'] = d.meta['unit'][1]
            ts_data['mod_freq_src'] = d.meta['ts_type_src'][1]
            
            stat_lat = np.float64(arr.latitude[i])
            stat_lon = np.float64(arr.longitude[i])
            if 'altitude' in arr.coords:
                stat_alt = np.float64(arr.altitude[i])
            else:
                stat_alt = np.nan
            region = find_closest_region_coord(stat_lat, stat_lon)
            
            # station information for map view
            map_stat = {'site'      : stat_name, 
                        'lat'       : stat_lat, 
                        'lon'       : stat_lon,
                        'alt'       : stat_alt,
                        'region'    : region}
            
            for tres, arr in data_arrs.items():
                map_stat['{}_statistics'.format(tres)] = {}
                if arr is None:
                    ts_data['{}_date'.format(tres)] = []
                    ts_data['{}_obs'.format(tres)] = []
                    ts_data['{}_mod'.format(tres)] = []
                    map_stat['{}_statistics'.format(tres)].update(stats_dummy)
                    continue
                
                obs_vals = arr.sel(data_source=obs_id, station_name=stat_name).values
                if all(np.isnan(obs_vals)):
                    print('No obs data: {} ({}, {})'.format(stat_name,
                                                            obs_var, obs_name))
                    ts_data['{}_date'.format(tres)] = []
                    ts_data['{}_obs'.format(tres)] = []
                    ts_data['{}_mod'.format(tres)] = []
                    map_stat['{}_statistics'.format(tres)].update(stats_dummy)
                    continue
                has_data = True
                mod_vals = arr.sel(data_source=model_id, station_name=stat_name).values
                if not len(jsdate[tres]) == len(obs_vals):
                    raise Exception('Please debug...')
                
                ts_data['{}_date'.format(tres)] = jsdate[tres]
                ts_data['{}_obs'.format(tres)] = obs_vals.tolist()
                ts_data['{}_mod'.format(tres)] = mod_vals.tolist()
                
                station_statistics = calc_statistics(mod_vals, obs_vals)
                for k, v in station_statistics.items():
                    station_statistics[k] = np.float64(v)
                map_stat['{}_statistics'.format(tres)] = station_statistics
            
            if has_data:
                ts_objs.append(ts_data)
                map_data.append(map_stat)
                scat_data[str(stat_name)] = sc = {}
                sc['obs'] = ts_data['monthly_obs']
                sc['mod'] = ts_data['monthly_mod']
                sc['region'] = region
        
        dirs = self.out_dirs
    
        map_name = self.get_json_mapname(obs_name, obs_var, model_name, 
                                         model_var, vert_code)
        
        outfile_map =  os.path.join(dirs['map'], map_name)
        with open(outfile_map, 'w') as f:
            simplejson.dump(map_data, f, ignore_nan=True)
        
        outfile_scat =  os.path.join(dirs['scat'], map_name)
        with open(outfile_scat, 'w') as f:
            simplejson.dump(scat_data, f, ignore_nan=True)
            
        for ts_data in ts_objs:
            #writes json file
            self._write_stationdata_json(ts_data)
         
    def get_vert_code(self, obs_name, obs_var):
        """Get vertical code name for obs / var combination"""
        info =  self.obs_config[obs_name]['obs_vert_type']
        if isinstance(info, str):
            return info
        return info[obs_var]
    
    def _write_stationdata_json(self, ts_data):
        
        filename = self.get_stationfile_name(ts_data['station_name'], 
                                             ts_data['obs_name'],
                                             ts_data['obs_var'],
                                             ts_data['vert_code'])
    
        fp = os.path.join(self.out_dirs['ts'], filename)
        if os.path.exists(fp):
             with open(fp, 'r') as f:
                current = simplejson.load(f)
        else:
            current = {}
        current[ts_data['model_name']] = ts_data
        with open(fp, 'w') as f:
            simplejson.dump(current, f, ignore_nan=True)
            
    def get_stationfile_name(self, station_name, obs_name, obs_var, vert_code):
        """Get name of station timeseries file"""
        return ('{}_OBS-{}:{}_{}.json'
                .format(station_name, obs_name, obs_var, vert_code))
    
    
    def get_json_mapname(self, obs_name, obs_var, model_name, model_var, 
                           vert_code):
        """Get name base name of json file""" 
        return ('OBS-{}:{}_{}_MOD-{}:{}.json'
                .format(obs_name, obs_var, vert_code, model_name, model_var))
        
    def make_json_files(self, model_name, obs_name):
        """Convert colocated data file(s) in model data directory into json
        
        Parameters
        ----------
        model_name : str
            name of model run
        obs_name : str
            name of observation network
        """
        if self.clear_existing_json:
            for f in glob.glob('{}/**/*OBS-{}*MOD-{}*.json'
                               .format(self.exp_dir, obs_name, model_name)):
                print('DELETING: {}'.format(os.path.basename(f)))
                os.remove(f)
        converted = []
        model_id = self.get_model_id(model_name)
        obs_id = self.get_obs_id(obs_name)
        
        files = glob.glob('{}/{}/*REF-{}*.nc'.format(self.coldata_dir, 
                                                     model_id, obs_id))
        if len(files) == 0:
            msg = 'Could not find any colocated data files for model {}'.format(model_id)
            if self.colocation_settings['raise_exceptions']:
                raise IOError(msg)
            else:
                self._log.warning(msg)
        for file in files:
            print('Processing file {}'.format(file))
            d = ColocatedData(file)
            self.compute_json_files_from_colocateddata(d)
            converted.append(file)
        return converted
    
    def delete_all_colocateddata_files(self, model_name, obs_name):
        model_id = self.get_model_id(model_name)
        obs_id = self.get_obs_id(obs_name)
        obs_vars = self.obs_config[obs_name]['obs_vars']
    
        for obs_var in obs_vars:
            files = glob.glob('{}/{}/{}*REF-{}*.nc'
                              .format(self.coldata_dir, model_id, obs_var, 
                                      obs_id))
            for file in files:
                print('DELETING FILE: {}'.format(file))
                os.remove(file)
            
    def run_colocation(self, model_name, obs_name):
        if self.colocation_settings['reanalyse_existing']:
            self.delete_all_colocateddata_files(model_name, obs_name)
            
        col = Colocator()
        col.update(**self.colocation_settings)
        
        if not model_name in self.model_config:
            raise KeyError('No such model name in configuration: {}. Available '
                           'names: {}'.format(model_name, 
                                              self.all_model_names))
        elif not obs_name in self.obs_config:
            raise KeyError('No such obs name in configuration: {}. Available '
                           'names: {}'.format(obs_name, self.all_obs_names))
            
        col.update(**self.obs_config[obs_name])
        col.update(**self.get_model_config(model_name))
    
        col.run()
        
        return col
    
    def get_model_config(self, model_name):
        """Get model configuration
        
        Since the configuration files for experiments are in json format, they
        do not allow the storage of executable custom methods for model data
        reading. Instead, these can be specified in a python module that may
        be specified via :attr:`add_methods_file` and that contains a 
        dictionary `FUNS` that maps the method names with the callable methods.
        
        As a result, this means that, by default, custom read methods for 
        individual models in :attr:`model_config` do not contain the 
        callable methods but only the names. This method will take care of 
        handling this and will return a dictionary where potential custom 
        method strings have been converted to the corresponding callable 
        methods.
        
        Parameters
        ----------
        model_name : str
            name of model run
            
        Returns 
        -------
        dict
            Dictionary that specifies the model setup ready for the analysis
        """
        mcfg = self.model_config[model_name]
        outcfg = {}
        if not 'model_id' in mcfg:
            raise ValueError('Model configuration for {} is missing '
                             'specification of model_id '.format(model_name))
        for key, val in mcfg.items():
            
            if key != 'model_read_aux':
                outcfg[key] = val
            else:
                outcfg[key] = d = {}
                for var, rcfg in val.items():
                    d[var] = {}
                    d[var]['vars_required'] = rcfg['vars_required']
                    fun_str = rcfg['fun']
                    if not isinstance(fun_str, str):
                        raise Exception('Unexpected error. Custom method defs. '
                                        'need to be strings, got {}'.format(fun_str))
                    d[var]['fun'] = self.get_custom_read_method_model(fun_str)
        return outcfg
            
    def find_model_matches(self, name_or_pattern):
        """Find model names that match input search pattern(s)
        
        Parameters
        ----------
        name_or_pattern : :obj:`str`, or :obj:`list`
            Name or pattern specifying model search string. Can also be a list 
            of names or patterns to search for multiple models.
            
        Returns
        -------
        list
            list of model names (i.e. keys of :attr:`model_config`) that match 
            the input search string(s) or pattern(s)
            
        Raises
        ------
        KeyError
            if no matches can be found
        """
        
        
        if isinstance(name_or_pattern, str):
            name_or_pattern = [name_or_pattern]
        from fnmatch import fnmatch
        matches = []
        for search_pattern in name_or_pattern:
            for mname in self.model_config:
                if fnmatch(mname, search_pattern) and not mname in matches:
                    matches.append(mname)
        if len(matches) == 0:
            raise KeyError('No models could be found that match input {}'
                           .format(name_or_pattern))
        return matches
    
    def find_obs_matches(self, name_or_pattern):
        """Find model names that match input search pattern(s)
        
        Parameters
        ----------
        name_or_pattern : :obj:`str`, or :obj:`list`
            Name or pattern specifying obs search string. Can also be a list 
            of names or patterns to search for multiple obs networks.
            
        Returns
        -------
        list
            list of model names (i.e. keys of :attr:`obs_config`) that match 
            the input search string(s) or pattern(s)
            
        Raises
        ------
        KeyError
            if no matches can be found
        """
        
        
        if isinstance(name_or_pattern, str):
            name_or_pattern = [name_or_pattern]
        matches = []
        for search_pattern in name_or_pattern:
            for mname in self.obs_config:
                if fnmatch(mname, search_pattern) and not mname in matches:
                    matches.append(mname)
        if len(matches) == 0:
            raise KeyError('No models could be found that match input {}'
                           .format(name_or_pattern))
        return matches
    
    def run_evaluation(self, model_name=None, obs_name=None, update_menu=True, 
                       reanalyse_existing=None, raise_exceptions=None, 
                       clear_existing_json=None, only_colocation=None):
        """Create colocated data and json files for model / obs combination
        
        Parameters
        ----------
        model_name : :obj:`str`, or :obj:`list`, optional
            Name or pattern specifying model that is supposed to be analysed.
            Can also be a list of names or patterns to specify multiple models.
            If None (default), then all models are run that are part of this
            experiment.
        obs_name : :obj:`str`, or :obj:`list`, optional
            Like :attr:`model_name`, but for specification(s) of observations
            that are supposed to be used.
        update_menu : bool
            if true, the menu.json file will be automatically updated after the
            run and also, the model info table (minfo.json) file is created and
            saved in :attr:`exp_dir`.
        """
        
        if reanalyse_existing is not None:
            self.colocation_settings['reanalyse_existing'] = reanalyse_existing
        if raise_exceptions is not None:
            self.colocation_settings['raise_exceptions'] = raise_exceptions
        if clear_existing_json is not None:
            self.clear_existing_json = clear_existing_json
        if only_colocation is not None:
            self.only_colocation = only_colocation
        
        if model_name is None:
            model_list = list(self.model_config)
        else:
            model_list = self.find_model_matches(model_name)
        
        if obs_name is None:
            obs_list = list(self.obs_config)
        else:
            obs_list = self.find_obs_matches(obs_name)
        self._log.info(self.info_string_evalrun(obs_list, model_list))
        
        self._update_custom_read_methods()
        
        for obs_name in obs_list:
            if obs_name in self.obs_ignore:
                self._log.info('Skipping observation {}'.format(obs_name))
                continue
            for model_name in model_list:
                if model_name in self.model_ignore:
                    self._log.info('Skipping model {}'.format(model_name))
                    continue
            
                self.run_colocation(model_name, obs_name)
                if only_colocation:
                    self._log.info('Skipping computation of json files for {}'
                                   '/{}'.format(obs_name, model_name))
                    continue
                res = self.make_json_files(model_name, obs_name)
        
        if update_menu:
            self.update_menu()
            self.make_info_table_web()
        return res            
        
    def info_string_evalrun(self, obs_list, model_list):
        """Short information string that summarises settings for evaluation run
        
        Parameters
        ----------
        obs_list
            list of observation names supposed to be processed
        model_list : list
            list of model names supposed to be processed
            
        Returns
        -------
        str
            info string
        """
        s = ('\nRunning analysis:\n'
             'Obs. names: {}\n'
             'Model names: {}\n'
             'Remove outliers: {}\n'
             'Harmonise units: {}'
             .format(obs_list, model_list, self['remove_outliers'], 
                     self['harmonise_units']))
        for k, i in self._OPTS_NAMES_OUTPUT.items():
            s += '\n{}: {}'.format(i, self[k]) 
        s += '\n'
        return s
    
    def get_web_overview_table(self):
        """Computes overview table based on existing map files"""
        tab = []
        from pandas import DataFrame
        for f in self.all_map_files:
            if f.endswith('.json') and f.startswith('OBS'):
                obs_info = f.split('OBS-')[1].split('_MOD')[0].split('_')
                obs_name, obs_var = obs_info[0].split(':')
                vert_code = obs_info[1]
                mod_name, mod_var =  f.split('MOD-')[1].split('.json')[0].split(':')
                if not mod_name in self.model_ignore:
                    tab.append([obs_var, obs_name, vert_code, mod_name, mod_var])
        return DataFrame(tab, columns=['Obs.' , 'Obs. var', 'vert',
                                       'Model', 'Model var.'])
    
    def get_obsvar_name_and_type(self, obs_var):
        """Get menu name and type of observation variable
        
        Parameters
        ----------
        obs_var : str
            Name of observation variable
        
        Returns
        -------
        tuple
            2-element tuple, containing:
                
                - :obj:`str`: menu name of this variable
                - :obj:`str`: menu category of this variable
        """
        try:
            name, tp = self.var_mapping[obs_var]
        except:
            name, tp = obs_var, 'n/a'
            self._log.warning('Missing menu name definition for var {}. '
                              'Using variable name'.format(obs_var))
        return (name, tp)
    
    def update_menu(self, **opts):
        """Updates menu.json based on existing map json files"""
        update_menu(self, **opts)
        
    def make_info_table_web(self):
        """Make and safe table with detailed infos about processed data files
        
        The table is stored in as file minfo.json in directory :attr:`exp_dir`.
        """
        table = make_info_table(self)
        outname = os.path.join(self.exp_dir, 'minfo.json')       
        with open(outname, 'w+') as f:
            f.write(simplejson.dumps(table, indent=2))
        return table
    
    def _obs_config_asdict(self):
        d = {}
        for k, cfg in self.obs_config.items():
            as_dict = {}
            as_dict.update(**cfg)
            d[k] = as_dict
        return d
    
    def _model_config_asdict(self):
        d = {}
        for k, cfg in self.model_config.items():
            as_dict = {}
            as_dict.update(**cfg)
            d[k] = as_dict
        return d        
    
    def to_dict(self):
        """Convert configuration to dictionary"""
        d = {}
        for key, val in self.__dict__.items():
            if key in self.JSON_CFG_IGNORE:
                continue
            elif isinstance(val, dict):
                if key == 'model_config':
                    sub = self._model_config_asdict()
                elif key == 'obs_config':
                    sub = self._obs_config_asdict()
                else:
                    sub = {}
                    for k, v in val.items():
                        if v is not None:
                            sub[k] = v
                d[key] = sub
            else:
                d[key] = val
        return d
    
    def to_json(self, output_dir):
        """Convert configuration to json ini file"""
        d = self.to_dict()
        out_name = 'cfg_{}_{}.json'.format(self.proj_id, self.exp_id)
        
        save_dict_json(d, os.path.join(output_dir, out_name), indent=3)
        return d
        
    def load_config(self, proj_id, exp_id, config_dir=None):
        """Load configuration json file"""
        if config_dir is None:
            if self.config_dir is not None:
                config_dir = self.config_dir
            else:
                config_dir = '.'
        files = glob.glob('{}/cfg_{}_{}.json'.format(config_dir, proj_id, 
                          exp_id))
        if len(files) == 0:
            raise ValueError('No config file could be found in {} for '
                             'project {} and experiment {}'.format(config_dir, 
                              proj_id, exp_id))
        self.from_json(files[0])
        print(self)
        
    def from_json(self, config_file):
        """Load configuration from json config file"""
        with open(config_file, 'r') as f:
            current = simplejson.load(f)
        self.update(**current)
        
    def __str__(self):
        indent = 2
        _indent_str = indent*' '
        head = "Pyaerocom {}".format(type(self).__name__)
        s = "\n{}\n{}".format(head, len(head)*"-")
        s += ('\nProject ID: {}'
              '\nEperiment ID: {}'
              '\nExperiment name: {}'
              .format(self.proj_id, self.exp_id, self.exp_name))
        s += '\ncolocation_settings:'
        for k, v in self.colocation_settings.items():
            s += '\n{}{}: {}'.format(_indent_str, k, v)
        s += '\n\nobs_config:'
        for k, v in self.obs_config.items():
            s += '\n\n{}{}:'.format(_indent_str, k)
            s = dict_to_str(v, s, indent=indent+2)
        s += '\n\nmodel_config:'
        for k, v in self.model_config.items():
            s += '\n\n{}{}:'.format(_indent_str,  k)
            s = dict_to_str(v, s, indent=indent+2)
    
        return s
    
if __name__ == '__main__':    
    cfg_dir = '/home/jonasg/github/aerocom_evaluation/data_new/config_files/'
    stp = AerocomEvaluation('aerocom', 'PIII-optics', config_dir=cfg_dir)
    stp.make_info_table_web()