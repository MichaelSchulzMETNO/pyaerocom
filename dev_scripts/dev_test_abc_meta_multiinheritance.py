#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test ABC meta and multiple inheritance


"""
import abc
import numpy as np

class GridDataBase(abc.ABC):
    def __init__(self, input, var_name, **kwargs):
        
        self._grid = None
        self.var_name = var_name
        self.metadata = {}
        
        self.load_input(input, var_name)
        self.metadata.update(**kwargs)
        
        super(GridDataBase, self).__init__()
    
    @abc.abstractproperty
    def grid(self):
        return self._grid
    
    @abc.abstractmethod
    def load_input(self, input, var_name):
        pass
    
    
    

class GridDataCF(abc.ABC):
    
    @abc.abstractclassmethod
    def longitude(self):
        pass

    @abc.abstractclassmethod
    def latitude(self):
        pass
    
    @abc.abstractclassmethod
    def time(self):
        pass

class GridData(GridDataBase, GridDataCF):
    
    def load_input(self, input, var_name):
        try:
            if np.sum(input.shape) > 0:
                self._grid = input
                self.var_name = var_name
        except:
            print("Failed to load input...")
    
    @property
    def grid(self):
        return self._grid
    
    @property
    def latitude(self):
        return 10
    
    @property
    def longitude(self):
        return 20
    
    @property
    def time(self):
        return 30
    
    @classmethod
    def from_scratch(cls, array):
        return cls(input=array, var_name="from_scratch")
            

class GridDataUncomplete(GridDataBase, GridDataCF):
    """Same as GridData but missing implementations of longitude and time
    methods"""
    
    
    def load_input(self, input, var_name):
        try:
            if np.sum(input.shape) > 0:
                self._grid = input
                self.var_name = var_name
        except:
            print("Failed to load input...")
    
    @property
    def latitude(self):
        return 10
        
    
if __name__ == "__main__":
    
    test_data = np.zeros((10,10))
    
    d = GridData(input = test_data, var_name="Bla")
    print(d.grid.shape, "\n",  d.var_name)
    print(d.latitude, d.longitude, d.time)
    
    d1 = GridData.from_scratch(test_data)
    print(d1.grid.shape, "\n",  d1.var_name)
    
    
    
    d1 = GridDataUncomplete(input=test_data, var_name="Bla")