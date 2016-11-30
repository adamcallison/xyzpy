""" Manage datasets --- loading, saving, merging etc. """

# TODO: add singlet dimensions (for all or given vars) ---------------------- #

from operator import eq
import numpy as np
import xarray as xr


_DEFAULT_FN_CACHE_PATH = '__xyz_cache__'


def cache_to_disk(fn=None, *, cachedir=_DEFAULT_FN_CACHE_PATH, **kwargs):
    import joblib
    mem = joblib.Memory(cachedir=cachedir, verbose=0, **kwargs)

    if fn:  # bare decorator
        return mem.cache(fn)
    else:  # called with kwargs
        def cache_to_disk_decorator(fn):
            return mem.cache(fn)
        return cache_to_disk_decorator


def _auto_add_extension(file_name, engine):
    """Make sure a file name has an extension that reflects its
    file type.
    """
    if "." not in file_name:
        extension = ".h5" if engine == "h5netcdf" else ".nc"
        file_name += extension
    return file_name


def save_ds(ds, file_name, engine="h5netcdf"):
    """Saves a xarray dataset.

    Parameters
    ----------
        ds: Dataset to save
        file_name: name of file to save to
        engine: engine used to save file

    Returns
    -------
        None
    """
    file_name = _auto_add_extension(file_name, engine)
    ds.to_netcdf(file_name, engine=engine)


def load_ds(file_name, engine="h5netcdf", load_to_mem=True, create_new=False):
    """Loads a xarray dataset.

    Parameters
    ----------
        file_name: name of file
        engine: engine used to load file
        load_to_mem: once opened, load from disk to memory
        create_new: if no file exists make a blank one

    Returns
    -------
        ds: loaded Dataset
    """
    file_name = _auto_add_extension(file_name, engine)
    try:
        try:
            ds = xr.open_dataset(file_name, engine=engine)
        except AttributeError as e1:
            if "object has no attribute" in str(e1) and engine == 'h5netcdf':
                ds = xr.open_dataset(file_name, engine="netcdf4")
            else:
                raise e1
        if load_to_mem:
            ds.load()
            ds.close()
    except (RuntimeError, OSError) as e2:
        if "o such" in str(e2) and create_new:
            ds = xr.Dataset()
        else:
            raise e2
    return ds


xrsave = save_ds
xrload = load_ds


def nonnull_compatible(first, second):
    """Check whether two (aligned) datasets have any conflicting values.
    """
    # TODO assert common coordinates are aligned?
    both_not_null = first.notnull() & second.notnull()
    return first.where(both_not_null).equals(second.where(both_not_null))


def aggregate(*datasets, overwrite=False, accept_newer=False):
    """Aggregates xarray Datasets and DataArrays

    Parameters
    ----------
        *datasets: sequence of datasets to combine
        overwrite: whether to overwrite conflicting values
        accept_newer: if overwriting whether to accept newer values, i.e.
            to prefer values in latter datasets.

    Returns
    -------
        ds: single Dataset containing data from all `datasets`
    """

    datasets = iter(datasets)
    ds1 = next(datasets)

    for ds2 in datasets:
        # Expand both to have same coordinates, padding with nan
        ds1, ds2 = (xr.align(ds1, ds2, join='outer') if accept_newer else
                    xr.align(ds2, ds1, join='outer'))

        # Check no data-loss will occur if overwrite not set
        if not overwrite and not nonnull_compatible(ds1, ds2):
            raise ValueError("Conflicting values in datasets. "
                             "Consider setting `overwrite=True`.")

        # Fill out missing values in initial dataset for common variables
        common_vars = (var for var in ds1.data_vars if var in ds2.data_vars)
        for var in common_vars:
            ds1[var] = ds1[var].fillna(ds2[var])

        # Add completely missing data_variables
        new_vars = (var for var in ds2.data_vars if var not in ds1.data_vars)
        for var in new_vars:
            ds1[var] = ds2[var]

        # TODO: check if result var is all non-nan and could be all same dtype
        # TODO:     - only really makes sense for int currently? and string?

    return ds1


def xrsmoosh(*objs, overwrite=False, accept_newer=False):
    try:
        return xr.merge(objs, compat='no_conflicts')
    except (ValueError, xr.MergeError):
        return aggregate(*objs, overwrite=overwrite, accept_newer=accept_newer)


def argwhere(x, y, key=eq):
    """Returns the first index of where y matches an element of x using key.
    """
    for i, el in enumerate(x):
        if key(el, y):
            return i


def gradient(xobj, dim, order=1, scale=True, ):
    """Calculate the central different gradient, by default scaled by dim.

    Paramters
    ---------
        xobj : xarray.DataArray or xarray.Dataset
            Object to find gradient for.
        dim : str
            Dimension to find gradient along.
        order : int
            How many times to differentiate.
        scale : bool (optional)
            Scale the gradients by the change in dim, i.e. emulate dy/dx

    Returns
    -------
        new_xobj : xarray.DataArray or xarray.Dataset
            Object now with gradients along `dim`.
    """
    def _single_gradient(xobj, dim, scale):
        if isinstance(xobj, xr.Dataset):
            for v in xobj.data_vars:
                if dim in xobj[v].dims:
                    axis = argwhere(xobj[v].dims, dim)
                    xobj[v].data = np.gradient(xobj[v].data, axis=axis)
        else:
            axis = argwhere(xobj.dims, dim)
            xobj.data = np.gradient(xobj.data, axis=axis)

        if scale:
            dx = np.gradient(xobj[dim])
            xobj['__diff__' + dim] = (dim, dx)
            xobj /= xobj['__diff__' + dim]
            xobj = xobj.drop('__diff__' + dim)

        return xobj

    new_xobj = xobj.copy(deep=True)
    for _ in range(order):
        new_xobj = _single_gradient(new_xobj, dim, scale)
    return new_xobj


def auto_xyz_ds(x, y_z):
    """Automatically turn an array into a `xarray` dataset.
    """
    # Infer dimensions to coords mapping
    y_z = np.array(np.squeeze(y_z), ndmin=2)
    if np.size(x) == y_z.shape[0]:
        y_z = np.transpose(y_z)
    n_y = y_z.shape[0]
    # Turn into dataset
    ds = xr.Dataset(coords={'x': x, 'z': np.arange(n_y)})
    ds['y'] = (('z', 'x'), y_z)
    return ds
