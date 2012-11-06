"""
Various utilities and cookbook-like things.
"""

from __future__ import division, with_statement, absolute_import

# STDLIB
import contextlib
from distutils import version
import io
import re
import sys


__all__ = [
    'convert_to_writable_filelike',
    'stc_reference_frames',
    'coerce_range_list_param',
    'is_callable'
    ]


IS_PY3K = sys.hexversion >= 0x03000000


@contextlib.contextmanager
def convert_to_writable_filelike(fd, compressed=False):
    """
    Returns a writable file-like object suitable for streaming output.

    Parameters
    ----------
    fd : file path string or writable file-like object
        May be:

            - a file path, in which case it is opened, and the file
              object is returned.

            - an object with a :meth:`write` method, in which case that
              object.

    compressed : bool, optional
        If `True`, create a gzip-compressed file.  (Default is `False`).

    Returns
    -------
    fd : writable file-like object
    """
    if isinstance(fd, basestring):
        if fd.endswith('.gz') or compressed:
            from ...utils.compat import gzip
            with gzip.GzipFile(fd, 'wb') as real_fd:
                encoded_fd = io.TextIOWrapper(real_fd, encoding='utf8')
                try:
                    yield encoded_fd
                finally:
                    encoded_fd.flush()
                    real_fd.flush()
                return
        else:
            with io.open(fd, 'wt', encoding='utf8') as real_fd:
                yield real_fd
                return
    elif hasattr(fd, 'write'):
        assert is_callable(fd.write)

        if compressed:
            from ...utils.compat import gzip
            fd = gzip.GzipFile(fileobj=fd)

        # If we can't write Unicode strings, use a codecs.StreamWriter
        # object
        needs_wrapper = False
        try:
            fd.write(u'')
        except TypeError:
            needs_wrapper = True

        if not hasattr(fd, 'encoding') or fd.encoding is None:
            needs_wrapper = True

        if needs_wrapper:
            import codecs
            try:
                yield codecs.getwriter('utf-8')(fd)
            finally:
                fd.flush()
        else:
            try:
                yield fd
            finally:
                fd.flush()

        return
    else:
        raise TypeError("Can not be coerced to writable file-like object")


# <http://www.ivoa.net/Documents/REC/DM/STC-20071030.html>
stc_reference_frames = set([
    'FK4', 'FK5', 'ECLIPTIC', 'ICRS', 'GALACTIC', 'GALACTIC_I', 'GALACTIC_II',
    'SUPER_GALACTIC', 'AZ_EL', 'BODY', 'GEO_C', 'GEO_D', 'MAG', 'GSE', 'GSM',
    'SM', 'HGC', 'HGS', 'HEEQ', 'HRTN', 'HPC', 'HPR', 'HCC', 'HGI',
    'MERCURY_C', 'VENUS_C', 'LUNA_C', 'MARS_C', 'JUPITER_C_III',
    'SATURN_C_III', 'URANUS_C_III', 'NEPTUNE_C_III', 'PLUTO_C', 'MERCURY_G',
    'VENUS_G', 'LUNA_G', 'MARS_G', 'JUPITER_G_III', 'SATURN_G_III',
    'URANUS_G_III', 'NEPTUNE_G_III', 'PLUTO_G', 'UNKNOWNFrame'])


def coerce_range_list_param(p, frames=None, numeric=True):
    """
    Coerces and/or verifies the object *p* into a valid range-list-format parameter.

    As defined in `Section 8.7.2 of Simple
    Spectral Access Protocol
    <http://www.ivoa.net/Documents/REC/DAL/SSA-20080201.html>`_.

    Parameters
    ----------
    p : str or sequence
        May be a string as passed verbatim to the service expecting a
        range-list, or a sequence.  If a sequence, each item must be
        either:

            - a numeric value

            - a named value, such as, for example, 'J' for named
              spectrum (if the *numeric* kwarg is False)

            - a 2-tuple indicating a range

            - the last item my be a string indicating the frame of
              reference

    frames : sequence of str, optional
        A sequence of acceptable frame of reference keywords.  If not
        provided, the default set in `set_reference_frames` will be
        used.

    numeric : bool, optional
        TODO

    Returns
    -------
    parts : tuple
        The result is a tuple:
            - a string suitable for passing to a service as a range-list
              argument

            - an integer counting the number of elements
    """
    def str_or_none(x):
        if x is None:
            return ''
        if numeric:
            x = float(x)
        return str(x)

    def numeric_or_range(x):
        if isinstance(x, tuple) and len(x) == 2:
            return '%s/%s' % (str_or_none(x[0]), str_or_none(x[1]))
        else:
            return str_or_none(x)

    def is_frame_of_reference(x):
        return isinstance(x, basestring)

    if p is None:
        return None, 0

    elif isinstance(p, (tuple, list)):
        has_frame_of_reference = len(p) > 1 and is_frame_of_reference(p[-1])
        if has_frame_of_reference:
            points = p[:-1]
        else:
            points = p[:]

        out = ','.join([numeric_or_range(x) for x in points])
        length = len(points)
        if has_frame_of_reference:
            if frames is not None and p[-1] not in frames:
                raise ValueError(
                    "'%s' is not a valid frame of reference" % p[-1])
            out += ';' + p[-1]
            length += 1

        return out, length

    elif isinstance(p, basestring):
        number = r'([-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?)?'
        if not numeric:
            number = r'(' + number + ')|([A-Z_]+)'
        match = re.match(
            '^' + number + r'([,/]' + number +
            r')+(;(?P<frame>[<A-Za-z_0-9]+))?$',
            p)

        if match is None:
            raise ValueError("'%s' is not a valid range list" % p)

        frame = match.groupdict()['frame']
        if frames is not None and frame is not None and frame not in frames:
            raise ValueError(
                "'%s' is not a valid frame of reference" % frame)
        return p, p.count(',') + p.count(';') + 1

    try:
        float(p)
        return str(p), 1
    except TypeError:
        raise ValueError("'%s' is not a valid range list" % p)


def version_compare(a, b):
    """
    Compare two VOTable version identifiers.
    """
    def version_to_tuple(v):
        if v[0].lower() == 'v':
            v = v[1:]
        return version.StrictVersion(v)
    av = version_to_tuple(a)
    bv = version_to_tuple(b)
    # Can't use cmp because it was removed from Python 3.x
    return (av > bv) - (av < bv)


if IS_PY3K:  # pragma: py3
    import collections

    def is_callable(o):
        """
        Returns `True` if `o` is callable.
        """
        return isinstance(o, collections.Callable)
else:  # pragma: py2
    def is_callable(o):
        """
        Returns `True` if `o` is callable.
        """
        return callable(o)
