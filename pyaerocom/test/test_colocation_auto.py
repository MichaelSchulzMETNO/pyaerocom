import pytest

import pyaerocom as pya
from pyaerocom import Colocator
from pyaerocom import ColocatedData

from pyaerocom.conftest import TESTDATADIR, TEST_PATHS
from pyaerocom.conftest import does_not_raise_exception
from pyaerocom.conftest import testdata_unavail



def test_colocator():
    col = Colocator(raise_exceptions=True)
    assert isinstance(col, Colocator)

    col = Colocator(obs_vars='obs_vars')
    assert isinstance(col.obs_vars, list)



    # col = Colocator(raise_exceptions=True)
    # col.obs_vars = 'obs_vars'
    # assert isinstance(col.obs_vars, list)
    # Hide properties that has differing behaviour when set after init?

def test_colocator_init_basedir_coldata(tmpdir):
    basedir = os.path.join(tmpdir, 'basedir')
    col = Colocator(basedir_coldata=basedir)
    assert os.path.isdir(basedir)

from pyaerocom.io import ReadGridded
from pyaerocom.exceptions import DataCoverageError
def test_colocator__find_var_matches():
    col = Colocator(raise_exceptions=True)
    r = ReadGridded('TM5-met2010_CTRL-TEST')
    with pytest.raises(DataCoverageError):
        col._find_var_matches('invalid', r)

    var_matches = col._find_var_matches('od550aer', r)
    assert var_matches == {'od550aer': 'od550aer'}

    obs_var = 'conco3'
    col = Colocator(obs_vars=obs_var)
    col.model_use_vars = {obs_var : 'od550aer'}
    var_matches = col._find_var_matches('conco3', r)
    # assert var_matches == {'conco3' : 'od550aer'} # hmm, other way round then?
    assert var_matches == {'od550aer' : 'conco3'} # Think the first comment in function contradicts this.


from pyaerocom import GriddedData
def test_colocator_read_model_data():
    col = Colocator(raise_exceptions=True)
    model_id = 'TM5-met2010_CTRL-TEST'
    col.model_id = model_id
    data = col.read_model_data('od550aer')
    assert isinstance(data, GriddedData)
    # pass # Never called

def test_colocator__check_add_model_read_aux():
    from pyaerocom.io.aux_read_cubes import add_cubes
    col = Colocator(raise_exceptions=True)
    r = ReadGridded('TM5-met2010_CTRL-TEST')
    assert not col._check_add_model_read_aux('od550aer', r)

    col.model_read_aux = {
        'od550aer' : dict(
            vars_required = ['od550aer', 'od550aer'],
            fun=add_cubes)}
    assert col._check_add_model_read_aux('od550aer', r)


@testdata_unavail
def test_colocator__coldata_savename(data_tm5):
    col = Colocator(raise_exceptions=True)
    col.obs_name = 'obs'
    col.model_name = 'model'
    col.ts_type = 'monthly'
    col.filter_name = 'WORLD'
    savename = col._coldata_savename(data_tm5)
    assert isinstance(savename, str)
    assert savename == 'od550aer_REF-obs_MOD-model_20100101_20101231_monthly_WORLD.nc'
# (self, model_data, start=None, stop=None,
                       # ts_type=None, var_name=None

from pyaerocom import UngriddedData
def test_colocator_read_ungridded():
    col = Colocator(raise_exceptions=True)
    obs_id = 'AeronetSunV3L2Subset.daily'
    obs_var = 'od550aer'
    col.obs_filters = {'longitude' : [-30, 30]}
    col.obs_id = obs_id
    col.read_opts_ungridded = {'last_file' : 10}
    # with pytest.raises(DataCoverageError):
        # data = col.read_ungridded(obs_var) # Why is this raised? Variable can be read in other tests..
        # read_ungridded expects a list of one or more variables! Should check for str and convert to list?
    data = col.read_ungridded([obs_var])
    assert isinstance(data, UngriddedData)

    col.read_opts_ungridded = None
    col.obs_vars = ['od550aer']
    with does_not_raise_exception():
        data = col.read_ungridded()
    col.obs_vars = ['invalid']
    with pytest.raises(DataCoverageError):
        data = col.read_ungridded()
    # pass # Never called

def test_colocator_update(tmpdir):
    col = Colocator(raise_exceptions=True)
    col.update(test = "test")
    assert col.test == 'test'

    obs_id = 'test'
    col.update(obs_id=obs_id)
    assert col.obs_id == obs_id

    basedir = os.path.join(tmpdir, 'basedir')
    assert not os.path.isdir(basedir)
    col.update(basedir_coldata=basedir)
    assert os.path.isdir(basedir)

def test_colocator_run():
    col = Colocator(raise_exceptions=True)
    # run_gridded_gridded
    pya.const.add_data_search_dir(TESTDATADIR.joinpath('obsdata'))
    model_id = 'TM5-met2010_CTRL-TEST'
    obs_id = 'TM5-met2010_CTRL-TEST'
    obs_vars = 'od550aer'
    col.model_id = model_id
    col.obs_id = obs_id
    col.raise_exceptions = True
    col.reanalyse_existing = True
    col.model_to_stp = True
    col.start = 2010 # col.start need to be set?
    col.obs_vars = obs_vars # Fails without this?
    col.run()
    assert isinstance(col.data[model_id][obs_vars], ColocatedData)

    # run_gridded_ungridded
    obs_id = 'AeronetSunV3L2Subset.daily'
    col = Colocator(raise_exceptions=True)
    obs_vars = 'od550aer'
    col.model_id = model_id
    col.obs_id = obs_id
    col.raise_exceptions = True
    col.reanalyse_existing = True
    col.start = 2010 # col.start need to be set?
    col.obs_vars = obs_vars # Fails without this?
    # col.model_to_stp = True # Fails, need lustre access
    col.run()
    assert isinstance(col.data[model_id][obs_vars], ColocatedData)

def test__run_gridded_ungridded():
    col = Colocator(raise_exceptions=True)
    pya.const.add_data_search_dir(TESTDATADIR.joinpath('obsdata'))

    model_id = 'TM5-met2010_CTRL-TEST'
    obs_id = 'AeronetSunV3L2Subset.daily'
    obs_vars = 'od550aer'
    col.model_id = model_id
    col.obs_id = obs_id
    col.raise_exceptions = True
    col.reanalyse_existing = True
    col.start = 2010
    col.obs_vars = obs_vars
    colocated_dict = col._run_gridded_ungridded()
    assert isinstance(colocated_dict[obs_vars], ColocatedData)

def test_colocator_output_dir():
    col = Colocator(raise_exceptions=True)
    with pytest.raises(AttributeError):
        col.output_dir('task') # This function is never used. Delete?


def test__run_gridded_gridded():
    col = Colocator(raise_exceptions=True, start=2010)
    obs_vars = 'od550aer'
    col.obs_vars = obs_vars

    pya.const.add_data_search_dir(TESTDATADIR.joinpath('obsdata'))
    model_id = 'TM5-met2010_CTRL-TEST'
    col.model_id = model_id
    col.obs_id = model_id
    col.raise_exceptions = True
    col.reanalyse_existing = True
    col.start = 2010
    col.obs_vars = obs_vars
    colocated_dict = col._run_gridded_gridded(obs_vars)
    assert isinstance(colocated_dict[obs_vars], ColocatedData)
    assert isinstance(col.data, dict)
    assert col.data == {}

def test_colocator_filter_name():
    with does_not_raise_exception():
        col = Colocator(filter_name='WORLD')
    with pytest.raises(Exception):
        col = Colocator(filter_name='invalid')

import os
# def test_colocator_basedir_coldata():
#     tmp_dir = '/tmp/pyaerocom'
#     try:
#         os.rmdir(tmp_dir)
#     except Exception as e:
#         print(e)
#     assert not os.path.isdir(tmp_dir)
#     col = Colocator(raise_exceptions=True)
#     col.basedir_coldata (basedir_coldata=tmp_dir)
#     assert os.path.isdir(tmp_dir)


def test_colocator_call():
    col = Colocator(raise_exceptions=True)
    with pytest.raises(NotImplementedError):
        col()
    # Delete __call__?

def test_colocator_dir():
    col = Colocator(raise_exceptions=True)
    assert isinstance(dir(col), list)

def test_colocator__find_var_matches_OLD():
    pass # Never called, delete?


# Test self.file_status
# exists
# exists_not
# saved
# skipped




# Refactor this?
# if self.raise_exceptions:
#     self._close_log()
#     raise Exception(msg)
#
# def if_raise_exception_close_log_and_raise_exception(msg):
#   if self.raise_exceptions()
#       self._close_log()
#       raise Exception(msg)
#
# def close_lag_and_raise_exception()
#   self._close_log()
#   raise exception(msg)


# by -> base_year



if __name__ == '__main__':
    import sys
    pytest.main(sys.argv)
