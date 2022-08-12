# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/core.ipynb (unless otherwise specified).

__all__ = ['StatsForecast']

# Cell
import inspect
import logging
from copy import deepcopy
from functools import partial
from os import cpu_count
from typing import Any, Callable, List, Optional, Tuple

import numpy as np
import pandas as pd

# Internal Cell
logging.basicConfig(
    format='%(asctime)s %(name)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

# Internal Cell
class GroupedArray:

    def __init__(self, data, indptr):
        self.data = data
        self.indptr = indptr
        self.n_groups = self.indptr.size - 1

    def __getitem__(self, idx):
        if isinstance(idx, int):
            return self.data[self.indptr[idx] : self.indptr[idx + 1]]
        elif isinstance(idx, slice):
            idx = slice(idx.start, idx.stop + 1, idx.step)
            new_indptr = self.indptr[idx].copy()
            new_data = self.data[new_indptr[0] : new_indptr[-1]].copy()
            new_indptr -= new_indptr[0]
            return GroupedArray(new_data, new_indptr)
        raise ValueError(f'idx must be either int or slice, got {type(idx)}')

    def __len__(self):
        return self.n_groups

    def __repr__(self):
        return f'GroupedArray(n_data={self.data.size:,}, n_groups={self.n_groups:,})'

    def __eq__(self, other):
        if not hasattr(other, 'data') or not hasattr(other, 'indptr'):
            return False
        return np.allclose(self.data, other.data) and np.array_equal(self.indptr, other.indptr)

    def fit(self, models):
        fm = np.full((self.n_groups, len(models)), np.nan, dtype=object)
        for i, grp in enumerate(self):
            y = grp[:, 0] if grp.ndim == 2 else grp
            X = grp[:, 1:] if (grp.ndim == 2 and grp.shape[1] > 1) else None
            for i_model, model in enumerate(models):
                new_model = model.new()
                fm[i, i_model] = new_model.fit(y=y, X=X)
        return fm

    def _get_cols(self, models, attr, h, X, level=tuple()):
        n_models = len(models)
        cuts = np.full(n_models + 1, fill_value=np.nan, dtype=np.int32)
        has_level_models = np.full(n_models, fill_value=False, dtype=bool)
        cuts[0] = 0
        for i_model, model in enumerate(models):
            len_cols = 1 # mean
            has_level = 'level' in inspect.signature(getattr(model, attr)).parameters and len(level) > 0
            has_level_models[i_model] = has_level
            if has_level:
                len_cols += 2 * len(level) #levels
            cuts[i_model + 1] = len_cols + cuts[i_model]
        return cuts, has_level_models

    def _output_fcst(self, models, attr, h, X, level=tuple()):
        #returns empty output according to method
        cuts, has_level_models = self._get_cols(models=models, attr=attr, h=h, X=X, level=level)
        out = np.full((self.n_groups * h, cuts[-1]), fill_value=np.nan, dtype=np.float32)
        return out, cuts, has_level_models

    def predict(self, fm, h, X=None, level=tuple()):
        #fm stands for fitted_models
        #and fm should have fitted_model
        fcsts, cuts, has_level_models = self._output_fcst(
            models=fm[0], attr='predict',
            h=h, X=X, level=level
        )
        matches = ['mean', 'lo', 'hi']
        cols = []
        for i_model in range(fm.shape[1]):
            has_level = has_level_models[i_model]
            kwargs = {}
            if has_level:
                kwargs['level'] = level
            for i, _ in enumerate(self):
                if X is not None:
                    X_ = X[i]
                else:
                    X_ = None
                res_i = fm[i, i_model].predict(h=h, X=X_, **kwargs)
                cols_m = [key for key in res_i.keys() if any(key.startswith(m) for m in matches)]
                fcsts_i = np.vstack([res_i[key] for key in cols_m]).T
                model_name = repr(fm[i, i_model])
                cols_m = [f'{model_name}' if col == 'mean' else f'{model_name}-{col}' for col in cols_m]
                if fcsts_i.ndim == 1:
                    fcsts_i = fcsts_i[:, None]
                fcsts[i * h : (i + 1) * h, cuts[i_model]:cuts[i_model + 1]] = fcsts_i
            cols += cols_m
        return fcsts, cols

    def fit_predict(self, models, h, X=None, level=tuple()):
        #fitted models
        fm = self.fit(models=models)
        #forecasts
        fcsts, cols = self.predict(fm=fm, h=h, X=X, level=level)
        return fm, fcsts, cols

    def forecast(self, models, h, fitted=False, X=None, level=tuple()):
        fcsts, cuts, has_level_models = self._output_fcst(
            models=models, attr='forecast',
            h=h, X=X, level=level
        )
        matches = ['mean', 'lo', 'hi']
        if fitted:
            #for the moment we dont return levels for fitted values in
            #forecast mode
            fitted_vals = np.full((self.data.shape[0], 1 + len(models)), np.nan, dtype=np.float32)
            if self.data.ndim == 1:
                fitted_vals[:, 0] = self.data
            else:
                fitted_vals[:, 0] = self.data[:, 0]
        for i, grp in enumerate(self):
            y_train = grp[:, 0] if grp.ndim == 2 else grp
            X_train = grp[:, 1:] if (grp.ndim == 2 and grp.shape[1] > 1) else None
            if X is not None:
                X_f = X[i]
            else:
                X_f = None
            cols = []
            for i_model, model in enumerate(models):
                has_level = has_level_models[i_model]
                kwargs = {}
                if has_level:
                    kwargs['level'] = level
                res_i = model.forecast(h=h, y=y_train, X=X_train, X_future=X_f, fitted=fitted, **kwargs)
                cols_m = [key for key in res_i.keys() if any(key.startswith(m) for m in matches)]
                fcsts_i = np.vstack([res_i[key] for key in cols_m]).T
                cols_m = [f'{repr(model)}' if col == 'mean' else f'{repr(model)}-{col}' for col in cols_m]
                if fcsts_i.ndim == 1:
                    fcsts_i = fcsts_i[:, None]
                fcsts[i * h : (i + 1) * h, cuts[i_model]:cuts[i_model + 1]] = fcsts_i
                cols += cols_m
                if fitted:
                    fitted_vals[self.indptr[i] : self.indptr[i + 1], i_model + 1] = res_i['fitted']
        result = {'forecasts': fcsts, 'cols': cols}
        if fitted:
            result['fitted'] = {'values': fitted_vals}
            result['fitted']['cols'] = ['y'] + [repr(model) for model in models]
        return result

    def cross_validation(self, models, h, test_size, step_size=1, input_size=None, fitted=False, level=tuple()):
        # output of size: (ts, window, h)
        if (test_size - h) % step_size:
            raise Exception('`test_size - h` should be module `step_size`')
        n_windows = int((test_size - h) / step_size) + 1
        n_models = len(models)
        cuts, has_level_models = self._get_cols(models=models, attr='forecast', h=h, X=None, level=level)
        # first column of out is the actual y
        out = np.full((self.n_groups, n_windows, h, 1 + cuts[-1]), np.nan, dtype=np.float32)
        if fitted:
            fitted_vals = np.full((self.data.shape[0], n_windows, n_models + 1), np.nan, dtype=np.float32)
            fitted_idxs = np.full((self.data.shape[0], n_windows), False, dtype=bool)
            last_fitted_idxs = np.full_like(fitted_idxs, False, dtype=bool)
        matches = ['mean', 'lo', 'hi']
        for i_ts, grp in enumerate(self):
            for i_window, cutoff in enumerate(range(-test_size, -h + 1, step_size), start=0):
                end_cutoff = cutoff + h
                in_size_disp = cutoff if input_size is None else input_size
                y = grp[(cutoff - in_size_disp):cutoff]
                y_train = y[:, 0] if y.ndim == 2 else y
                X_train = y[:, 1:] if (y.ndim == 2 and y.shape[1] > 1) else None
                y_test = grp[cutoff:] if end_cutoff == 0 else grp[cutoff:end_cutoff]
                X_future = y_test[:, 1:] if (y_test.ndim == 2 and y_test.shape[1] > 1) else None
                out[i_ts, i_window, :, 0] = y_test[:, 0] if y.ndim == 2 else y_test
                if fitted:
                    fitted_vals[self.indptr[i_ts] : self.indptr[i_ts + 1], i_window, 0][
                        (cutoff - in_size_disp):cutoff
                    ] = y_train
                    fitted_idxs[self.indptr[i_ts] : self.indptr[i_ts + 1], i_window][
                        (cutoff - in_size_disp):cutoff
                    ] = True
                    last_fitted_idxs[
                        self.indptr[i_ts] : self.indptr[i_ts + 1], i_window
                    ][cutoff-1] = True
                cols = ['y']
                for i_model, model in enumerate(models):
                    has_level = has_level_models[i_model]
                    kwargs = {}
                    if has_level:
                        kwargs['level'] = level
                    res_i = model.forecast(h=h, y=y_train, X=X_train, X_future=X_future, fitted=fitted, **kwargs)
                    cols_m = [key for key in res_i.keys() if any(key.startswith(m) for m in matches)]
                    fcsts_i = np.vstack([res_i[key] for key in cols_m]).T
                    cols_m = [f'{repr(model)}' if col == 'mean' else f'{repr(model)}-{col}' for col in cols_m]
                    out[i_ts, i_window, :, (1 + cuts[i_model]):(1 + cuts[i_model + 1])] = fcsts_i
                    if fitted:
                        fitted_vals[self.indptr[i_ts] : self.indptr[i_ts + 1], i_window, i_model + 1][
                            (cutoff - in_size_disp):cutoff
                        ] = res_i['fitted']
                    cols += cols_m
        result = {'forecasts': out.reshape(-1, 1 + cuts[-1]), 'cols': cols}
        if fitted:
            result['fitted'] = {
                'values': np.reshape(fitted_vals, (-1, n_models + 1), order='F'),
                'idxs': fitted_idxs.flatten(order='F'),
                'last_idxs': last_fitted_idxs.flatten(order='F'),
                'cols': ['y'] + [repr(model) for model in models]
            }
        return result

    def split(self, n_chunks):
        return [self[x[0] : x[-1] + 1] for x in np.array_split(range(self.n_groups), n_chunks) if x.size]

    def split_fm(self, fm, n_chunks):
        return [fm[x[0] : x[-1] + 1] for x in np.array_split(range(self.n_groups), n_chunks) if x.size]

# Internal Cell
def _grouped_array_from_df(df, sort_df):
    df = df.set_index('ds', append=True)
    if not df.index.is_monotonic_increasing and sort_df:
        df = df.sort_index()
    data = df.values.astype(np.float32)
    indices_sizes = df.index.get_level_values('unique_id').value_counts(sort=False)
    indices = indices_sizes.index
    sizes = indices_sizes.values
    cum_sizes = sizes.cumsum()
    dates = df.index.get_level_values('ds')[cum_sizes - 1]
    indptr = np.append(0, cum_sizes).astype(np.int32)
    return GroupedArray(data, indptr), indices, dates, df.index

# Internal Cell
def _cv_dates(last_dates, freq, h, test_size, step_size=1):
    #assuming step_size = 1
    if (test_size - h) % step_size:
        raise Exception('`test_size - h` should be module `step_size`')
    n_windows = int((test_size - h) / step_size) + 1
    if len(np.unique(last_dates)) == 1:
        if issubclass(last_dates.dtype.type, np.integer):
            total_dates = np.arange(last_dates[0] - test_size + 1, last_dates[0] + 1)
            out = np.empty((h * n_windows, 2), dtype=last_dates.dtype)
            freq = 1
        else:
            total_dates = pd.date_range(end=last_dates[0], periods=test_size, freq=freq)
            out = np.empty((h * n_windows, 2), dtype='datetime64[s]')
        for i_window, cutoff in enumerate(range(-test_size, -h + 1, step_size), start=0):
            end_cutoff = cutoff + h
            out[h * i_window : h * (i_window + 1), 0] = total_dates[cutoff:] if end_cutoff == 0 else total_dates[cutoff:end_cutoff]
            out[h * i_window : h * (i_window + 1), 1] = np.tile(total_dates[cutoff] - freq, h)
        dates = pd.DataFrame(np.tile(out, (len(last_dates), 1)), columns=['ds', 'cutoff'])
    else:
        dates = pd.concat([_cv_dates(np.array([ld]), freq, h, test_size, step_size) for ld in last_dates])
        dates = dates.reset_index(drop=True)
    return dates

# Internal Cell
def _get_n_jobs(n_groups, n_jobs, ray_address):
    if ray_address is not None:
        logger.info(
            'Using ray address,'
            'using available resources insted of `n_jobs`'
        )
        try:
            import ray
        except ModuleNotFoundError as e:
            msg = (
                f'{e}. To use a ray cluster you have to install '
                'ray. Please run `pip install ray`. '
            )
            raise ModuleNotFoundError(msg) from e
        if not ray.is_initialized():
            ray.init(ray_address, ignore_reinit_error=True)
        actual_n_jobs = int(ray.available_resources()['CPU'])
    else:
        if n_jobs == -1 or (n_jobs is None):
            actual_n_jobs = cpu_count()
        else:
            actual_n_jobs = n_jobs
    return min(n_groups, actual_n_jobs)

# Cell
class StatsForecast:

    def __init__(
            self,
            models: List[Tuple[Callable, Any]], # List of tuples, each containing a fn and its parameters
            freq: str, # Frequency of the data
            n_jobs: int = 1, # Number of jobs used to parallel processing. Use `-1` to use all cores
            ray_address: Optional[str] = None,  # Optional ray address to distribute jobs
            df: Optional[pd.DataFrame] = None, # DataFrame with columns `ds`, `y`, and exogenous variables, indexed by `unique_id`
            sort_df: bool = True # Sort `df` according to index and `ds`?
        ):
        # needed for residuals, think about it later
        self.models = models
        self.freq = pd.tseries.frequencies.to_offset(freq)
        self.n_jobs = n_jobs
        self.ray_address = ray_address
        self._prepare_fit(df=df, sort_df=sort_df)

    def _prepare_fit(self, df, sort_df):
        if df is not None:
            if df.index.name != 'unique_id':
                df = df.set_index('unique_id')
            self.ga, self.uids, self.last_dates, self.ds = _grouped_array_from_df(df, sort_df)
            self.n_jobs = _get_n_jobs(len(self.ga), self.n_jobs, self.ray_address)
            self.sort_df = sort_df

    def fit(
            self,
            df: Optional[pd.DataFrame] = None, # DataFrame with columns `ds`, `y`, and exogenous variables, indexed by `unique_id`
            sort_df: bool = True # Sort `df` according to index and `ds`?
        ):
        self._prepare_fit(df, sort_df)
        if self.n_jobs == 1:
            self.fitted_ = self.ga.fit(models=self.models)
        else:
            self.fitted_ = self._fit_parallel()
        #idx = pd.Index(self.uids, name='unique_id')
        #self.fitted_ = pd.DataFrame(self.fitted_, index=idx)
        return self

    def _make_future_df(self, h: int):
        if issubclass(self.last_dates.dtype.type, np.integer):
            last_date_f = lambda x: np.arange(x + 1, x + 1 + h, dtype=self.last_dates.dtype)
        else:
            last_date_f = lambda x: pd.date_range(x + self.freq, periods=h, freq=self.freq)
        if len(np.unique(self.last_dates)) == 1:
            dates = np.tile(last_date_f(self.last_dates[0]), len(self.ga))
        else:
            dates = np.hstack([
                last_date_f(last_date)
                for last_date in self.last_dates
            ])
        idx = pd.Index(np.repeat(self.uids, h), name='unique_id')
        df = pd.DataFrame({'ds': dates}, index=idx)
        return df

    def _parse_X_level(self, h, X, level):
        if X is not None:
            expected_shape = (h * len(self.ga), self.ga.data.shape[1])
            if X.shape != expected_shape:
                raise ValueError(f'Expected X to have shape {expected_shape}, but got {X.shape}')
            X, _, _, _ = _grouped_array_from_df(X, sort_df=self.sort_df)
        if level is None:
            level = tuple()
        return X, level

    def predict(
            self,
            h: int, # Forecast horizon,
            X: Optional[pd.DataFrame] = None, # Future exogenous regressors
            level: Optional[List[int]] = None, # Levels of propabilistic intervals
        ):
        X, level = self._parse_X_level(h=h, X=X, level=level)
        if self.n_jobs == 1:
            fcsts, cols = self.ga.predict(fm=self.fitted_, h=h, X=X, level=level)
        else:
            fcsts, cols = self._predict_parallel(h=h, X=X, level=level)
        df = self._make_future_df(h=h)
        df[cols] = fcsts
        return df

    def fit_predict(
            self,
            h: int, # Forecast horizon
            df: Optional[pd.DataFrame] = None, # DataFrame with columns `ds`, `y`, and exogenous variables, indexed by `unique_id`
            X: Optional[pd.DataFrame] = None, # Future exogenous regressors
            level: Optional[List[int]] = None, # Levels of propabilistic intervals
            sort_df: bool = True # Sort `df` according to index and `ds`?
        ):
        self._prepare_fit(df, sort_df)
        X, level = self._parse_X_level(h=h, X=X, level=level)
        if self.n_jobs == 1:
            self.fitted_, fcsts, cols = self.ga.fit_predict(models=self.models, h=h, X=X, level=level)
        else:
            self.fitted_, fcsts, cols = self._fit_predict_parallel(h=h, X=X, level=level)
        df = self._make_future_df(h=h)
        df[cols] = fcsts
        return df

    def forecast(
            self,
            h: int, # Forecast horizon
            df: Optional[pd.DataFrame] = None, # DataFrame with columns `ds`, `y`, and exogenous variables, indexed by `unique_id`
            X: Optional[pd.DataFrame] = None, # Future exogenous regressors
            level: Optional[List[int]] = None, # Levels of propabilistic intervals
            fitted: bool = False,
            sort_df: bool = True # Sort `df` according to index and `ds`?
        ):
        self._prepare_fit(df, sort_df)
        X, level = self._parse_X_level(h=h, X=X, level=level)
        if self.n_jobs == 1:
            res_fcsts = self.ga.forecast(models=self.models, h=h, fitted=fitted, X=X, level=level)
        else:
            res_fcsts = self._forecast_parallel(h=h, fitted=fitted, X=X, level=level)
        if fitted:
            self.fcst_fitted_values_ = res_fcsts['fitted']
        fcsts = res_fcsts['forecasts']
        cols = res_fcsts['cols']
        df = self._make_future_df(h=h)
        df[cols] = fcsts
        return df

    def forecast_fitted_values(self):
        if not hasattr(self, 'fcst_fitted_values_'):
            raise Exception('Please run `forecast` mehtod using `fitted=True`')
        cols = self.fcst_fitted_values_['cols']
        df = pd.DataFrame(self.fcst_fitted_values_['values'],
                          columns=cols,
                          index=self.ds).reset_index(level=1)
        return df

    def cross_validation(
            self,
            h: int, # Forecast horizon
            df: Optional[pd.DataFrame] = None, # DataFrame with columns `ds`, `y`, and exogenous variables, indexed by `unique_id`
            n_windows: int = 1, # Number of windows used for cross validation
            step_size: int = 1, # Step size between each window
            test_size: Optional[int] = None, # Lenght of test size. If passed, set `n_windows=None`
            input_size: Optional[int] = None, # Input size for each window
            level: Optional[List[int]] = None, # Levels of propabilistic intervals
            fitted=False, # Save fitted values for each window and each model?
            sort_df: bool = True # Sort `df` according to index and `ds`?
        ):
        if test_size is None:
            test_size = h + step_size * (n_windows - 1)
        elif n_windows is None:
            if (test_size - h) % step_size:
                raise Exception('`test_size - h` should be module `step_size`')
            n_windows = int((test_size - h) / step_size) + 1
        elif (n_windows is None) and (test_size is None):
            raise Exception('you must define `n_windows` or `test_size`')
        else:
            raise Exception('you must define `n_windows` or `test_size` but not both')
        self._prepare_fit(df, sort_df)
        _, level = self._parse_X_level(h=h, X=None, level=level)
        if self.n_jobs == 1:
            res_fcsts = self.ga.cross_validation(
                models=self.models, h=h, test_size=test_size,
                step_size=step_size,
                input_size=input_size,
                fitted=fitted,
                level=level
            )
        else:
            res_fcsts = self._cross_validation_parallel(
                h=h,
                test_size=test_size,
                step_size=step_size,
                input_size=input_size,
                fitted=fitted,
                level=level
            )

        if fitted:
            self.cv_fitted_values_ = res_fcsts['fitted']
            self.n_cv_ = n_windows

        fcsts = res_fcsts['forecasts']
        cols = res_fcsts['cols']
        df = _cv_dates(last_dates=self.last_dates, freq=self.freq, h=h, test_size=test_size, step_size=step_size)
        #dates = {'ds': dates['ds'].values, 'cutoff': dates['cutoff'].values}
        idx = pd.Index(np.repeat(self.uids, h * n_windows), name='unique_id')
        df.index = idx
        df[cols] = fcsts
        return df

    def cross_validation_fitted_values(self):
        if not hasattr(self, 'cv_fitted_values_'):
            raise Exception('Please run `cross_validation` mehtod using `fitted=True`')
        index = pd.MultiIndex.from_tuples(np.tile(self.ds, self.n_cv_), names=['unique_id', 'ds'])
        df = pd.DataFrame(index=index)
        df['cutoff'] = self.cv_fitted_values_['last_idxs']
        df[self.cv_fitted_values_['cols']] = self.cv_fitted_values_['values']
        idxs = self.cv_fitted_values_['idxs']
        df = df.iloc[idxs].reset_index(level=1)
        df['cutoff'] = df['ds'].where(df['cutoff']).bfill()
        return df

    def _get_pool(self):
        if self.ray_address is not None:
            try:
                from ray.util.multiprocessing import Pool
            except ModuleNotFoundError as e:
                msg = (
                    f'{e}. To use a ray cluster you have to install '
                    'ray. Please run `pip install ray`. '
                )
                raise ModuleNotFoundError(msg) from e
            pool_kwargs = dict(ray_address=self.ray_address)
        else:
            from multiprocessing import Pool
            pool_kwargs = dict()
        return Pool, pool_kwargs

    def _fit_parallel(self):
        gas = self.ga.split(self.n_jobs)
        Pool, pool_kwargs = self._get_pool()
        with Pool(self.n_jobs, **pool_kwargs) as executor:
            futures = []
            for ga in gas:
                future = executor.apply_async(ga.fit, (self.models,))
                futures.append(future)
            fm = np.vstack([f.get() for f in futures])
        return fm

    def _get_gas_Xs(self, X):
        gas = self.ga.split(self.n_jobs)
        if X is not None:
            Xs = X.split(self.n_jobs)
        else:
            from itertools import repeat
            Xs = repeat(None)
        return gas, Xs

    def _predict_parallel(self, h, X, level):
        #create elements for each core
        gas, Xs = self._get_gas_Xs(X=X)
        fms = self.ga.split_fm(self.fitted_, self.n_jobs)
        Pool, pool_kwargs = self._get_pool()
        #compute parallel forecasts
        with Pool(self.n_jobs, **pool_kwargs) as executor:
            futures = []
            for ga, fm, X_ in zip(gas, fms, Xs):
                future = executor.apply_async(ga.predict, (fm, h, X_, level,))
                futures.append(future)
            out = [f.get() for f in futures]
            fcsts, cols = list(zip(*out))
            fcsts = np.vstack(fcsts)
            cols = cols[0]
        return fcsts, cols

    def _fit_predict_parallel(self, h, X, level):
        #create elements for each core
        gas, Xs = self._get_gas_Xs(X=X)
        Pool, pool_kwargs = self._get_pool()
        #compute parallel forecasts
        with Pool(self.n_jobs, **pool_kwargs) as executor:
            futures = []
            for ga, X_ in zip(gas, Xs):
                future = executor.apply_async(ga.fit_predict, (self.models, h, X_, level,))
                futures.append(future)
            out = [f.get() for f in futures]
            fm, fcsts, cols = list(zip(*out))
            fm = np.vstack(fm)
            fcsts = np.vstack(fcsts)
            cols = cols[0]
        return fm, fcsts, cols

    def _forecast_parallel(self, h, fitted, X, level):
        #create elements for each core
        gas, Xs = self._get_gas_Xs(X=X)
        Pool, pool_kwargs = self._get_pool()
        #compute parallel forecasts
        result = {}
        with Pool(self.n_jobs, **pool_kwargs) as executor:
            futures = []
            for ga, X_ in zip(gas, Xs):
                future = executor.apply_async(ga.forecast, (self.models, h, fitted, X_, level,))
                futures.append(future)
            out = [f.get() for f in futures]
            fcsts = [d['forecasts'] for d in out]
            fcsts = np.vstack(fcsts)
            cols = out[0]['cols']
            result['forecasts'] = fcsts
            result['cols'] = cols
            if fitted:
                result['fitted'] = {}
                fitted_vals = [d['fitted']['values'] for d in out]
                result['fitted']['values'] = np.vstack(fitted_vals)
                result['fitted']['cols'] = out[0]['fitted']['cols']
        return result

    def _cross_validation_parallel(self, h, test_size, step_size, input_size, fitted, level):
        #create elements for each core
        gas = self.ga.split(self.n_jobs)
        Pool, pool_kwargs = self._get_pool()
        #compute parallel forecasts
        result = {}
        with Pool(self.n_jobs, **pool_kwargs) as executor:
            futures = []
            for ga in gas:
                future = executor.apply_async(
                    ga.cross_validation,
                    (self.models, h, test_size, step_size, input_size, fitted, level,)
                )
                futures.append(future)
            out = [f.get() for f in futures]
            fcsts = [d['forecasts'] for d in out]
            fcsts = np.vstack(fcsts)
            cols = out[0]['cols']
            result['forecasts'] = fcsts
            result['cols'] = cols
            if fitted:
                result['fitted'] = {}
                result['fitted']['values'] = np.vstack([d['fitted']['values'] for d in out])
                for key in ['last_idxs', 'idxs']:
                    result['fitted'][key] = np.hstack([d['fitted'][key] for d in out])
                result['fitted']['cols'] = out[0]['fitted']['cols']
        return result

    def __repr__(self):
        return f"StatsForecast(models=[{','.join(map(repr, self.models))}])"