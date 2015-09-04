""" Module for fitting a QSO continuum
"""
from __future__ import print_function, absolute_import, division, \
     unicode_literals

import warnings
import sys, os
import numpy as np

from ..utils import between
from .interp import AkimaSpline

def make_chunks_qso(wa, redshift, divmult=1, forest_divmult=1, debug=False):
    """ Generate a series of wavelength chunks for use by
    prepare_knots, assuming a QSO spectrum
    """

    zp1 = 1 + redshift
    #reflines = np.array([1025.72, 1215.6701, 1240.14, 1398.0,
    #                     1549.06, 1908,      2800            ])

    # generate the edges of wavelength chunks to send to fitting routine

    # these edges and divisions are generated by trial and error

    # for S/N = 15ish and resolution = 2000ish

    div = np.rec.fromrecords([(500. , 800. , 25),
                              (800. , 1190., 25),
                              (1190., 1213.,  4),
                              (1213., 1230.,  6),
                              (1230., 1263.,  6),
                              (1263., 1290.,  5),
                              (1290., 1340.,  5),
                              (1340., 1370.,  2),
                              (1370., 1410.,  5),
                              (1410., 1515.,  5),
                              (1515., 1600., 15),
                              (1600., 1800.,  8),
                              (1800., 1900.,  5),
                              (1900., 1940.,  5),
                              (1940., 2240., 15),
                              (2240., 3000., 25),
                              (3000., 6000., 80),
                              (6000., 20000., 100),
                              ], names=str('left,right,num'))

    div.num[2:] = np.ceil(div.num[2:] * divmult)
    div.num[:2] = np.ceil(div.num[:2] * forest_divmult)
    div.left *= zp1
    div.right *= zp1
    if debug:
        print(div.tolist())
    temp = [np.linspace(left, right, n+1)[:-1] for left,right,n in div]
    edges = np.concatenate(temp)

    i0,i1,i2 = edges.searchsorted([wa[0], 1210*zp1, wa[-1]])
    if debug:
        print(i0,i1,i2)
    return edges[i0:i2]


def update_knots(knots, indices, fl, masked):
    """ Calculate the y position of each knot. Updates inplace.

    Parameters
    ---------
    knots: list of [xpos, ypos, bool] with length N
      bool says whether the knot should kept unchanged.
    indices: list of (i0,i1) index pairs
       The start and end indices into fl and masked of each
       spectrum chunk (xpos of each knot are the chunk centres).
    fl, masked: arrays shape (M,)
       The flux, and boolean arrays showing which pixels are
       masked.
    """

    iy, iflag = 1, 2
    for iknot,(i1,i2) in enumerate(indices):
        if knots[iknot][iflag]:
            continue

        f0 = fl[i1:i2]
        m0 = masked[i1:i2]
        f1 = f0[~m0]
        knots[iknot][iy] = np.median(f1)


def linear_co(wa, knots):
    """linear interpolation through the spline knots.

    Add extra points on either end to give
    a nice slope at the end points."""
    wavc, mfl = zip(*knots)[:2]
    extwavc = ([wavc[0] - (wavc[1] - wavc[0])] + list(wavc) +
               [wavc[-1] + (wavc[-1] - wavc[-2])])
    extmfl = ([mfl[0] - (mfl[1] - mfl[0])] + list(mfl) +
              [mfl[-1] + (mfl[-1] - mfl[-2])])
    co = np.interp(wa, extwavc, extmfl)
    return co


def Akima_co(wa, knots):
    """Akima interpolation through the spline knots."""
    x,y,_ = zip(*knots)
    spl = AkimaSpline(x, y)
    return spl(wa)


def remove_bad_knots(knots, indices, masked, fl, er, debug=False):
    """ Remove knots in chunks without any good pixels. Modifies
    inplace."""
    idelknot = []
    for iknot,(i,j) in enumerate(indices):
        if np.all(masked[i:j]) or np.median(fl[i:j]) <= 2*np.median(er[i:j]):
            if debug:
                print('Deleting knot', iknot, 'near {:.1f} Angstroms'.format(
                    knots[iknot][0]))
            idelknot.append(iknot)

    for i in reversed(idelknot):
        del knots[i]
        del indices[i]


def chisq_chunk(model, fl, er, masked, indices, knots, chithresh=1.5):
    """ Calc chisq per chunk, update knots flags inplace if chisq is
    acceptable. """
    chisq = []
    FLAG = 2
    for iknot,(i1,i2) in enumerate(indices):
        if knots[iknot][FLAG]:
            continue

        f0 = fl[i1:i2]
        e0 = er[i1:i2]
        m0 = masked[i1:i2]
        f1 = f0[~m0]
        e1 = e0[~m0]
        mod0 = model[i1:i2]
        mod1 = mod0[~m0]
        resid = (mod1 - f1) / e1
        chisq = np.sum(resid*resid)
        rchisq = chisq / len(f1)
        if rchisq < chithresh:
            #print (good reduced chisq in knot', iknot)
            knots[iknot][FLAG] = True


def prepare_knots(wa, fl, er, edges, ax=None, debug=False):
    """ Make initial knots for the continuum estimation.

    Parameters
    ----------
    wa, fl, er : arrays
       Wavelength, flux, error.
    edges : The edges of the wavelength chunks. Splines knots are to be
       places at the centre of these chunks.
    ax : Matplotlib Axes
       If not None, use to plot debugging info.

    Returns
    -------
    knots, indices, masked

      knots: A list of [x, y, flag] lists giving the x and y position
      of each knot.

      indices: A list of tuples (i,j) giving the start and end index
      of each chunk.

      masked: An array the same shape as wa.
    """
    indices = wa.searchsorted(edges)
    indices = [(i0,i1) for i0,i1 in zip(indices[:-1],indices[1:])]
    wavc = [0.5*(w1 + w2) for w1,w2 in zip(edges[:-1],edges[1:])]

    knots = [[wavc[i], 0, False] for i in range(len(wavc))]

    masked = np.zeros(len(wa), bool)
    masked[~(er > 0)] = True

    # remove bad knots
    remove_bad_knots(knots, indices, masked, fl, er, debug=debug)

    if ax is not None:
        yedge = np.interp(edges, wa, fl)
        ax.vlines(edges, 0, yedge + 100, color='c', zorder=10)

    # set the knot flux values
    update_knots(knots, indices, fl, masked)

    if ax is not None:
        x,y = zip(*knots)[:2]
        ax.plot(x, y, 'o', mfc='none', mec='c', ms=10, mew=1, zorder=10)

    return knots, indices, masked


def unmask(masked, indices, wa, fl, er, minpix=3):
    """ Sometimes all pixels can become masked in a chunk. We don't
     want this!

     This forces there to be at least minpix pixels used in each chunk.
     """
    for iknot,(i,j) in enumerate(indices):
        #print(iknot, wa[i], wa[j], (~masked[i:j]).sum())
        if np.sum(~masked[i:j]) < minpix:
            #print('unmasking pixels')
            # need to unmask minpix
            f0 = fl[i:j]
            e0 = er[i:j]
            ind = np.arange(i,j)
            f1 = f0[e0 > 0]
            isort = np.argsort(f1)
            ind1 = ind[e0 > 0][isort[-minpix:]]
            #    print(wa[i], wa[j])
            #    print(wa[ind1])
            masked[ind1] = False


def estimate_continuum(s, knots, indices, masked, ax=None, maxiter=1000,
                       nsig=1.5, debug=False):
    """ Iterate to estimate the continuum.
    """
    count = 0
    while True:
        if debug:
            print('iteration', count)
        update_knots(knots, indices, s.fl, masked)
        model = linear_co(s.wa, knots)
        model_a = Akima_co(s.wa, knots)
        chisq_chunk(model_a, s.fl, s.er, masked,
                    indices, knots, chithresh=1)
        flags = zip(*knots)[-1]
        if np.all(flags):
            if debug:
                print('All regions have satisfactory fit, stopping')
            break
        # remove outliers
        c0 = ~masked
        resid = (model - s.fl) / s.er
        oldmasked = masked.copy()
        masked[(resid > nsig) & ~masked] = True
        unmask(masked, indices, s.wa, s.fl, s.er)
        if np.all(oldmasked == masked):
            if debug:
                print('No further points masked, stopping')
            break
        if count > maxiter:
            raise RuntimeError('Exceeded maximum iterations')

        count +=1

    co = Akima_co(s.wa, knots)
    c0 = co <= 0
    co[c0] = 0

    if ax is not None:
        ax.plot(s.wa, linear_co(s.wa, knots), color='0.7', lw=2)
        ax.plot(s.wa, co, 'k', lw=2, zorder=10)
        x,y = zip(*knots)[:2]
        ax.plot(x, y, 'o', mfc='none', mec='k', ms=10, mew=1, zorder=10)

    return co


def find_continuum(spec, edges=None, ax=None, debug=False, kind='QSO',
                   **kwargs):
    """ Estimate a continuum for a spectrum.

    Parameters
    ----------
    spec: XSpectrum1D object
      Wavelength, flux and one sigma error.
    kind : {'default', 'QSO'}
      Which kind of continuum to fit. This is used to generate a list
      of wavelength chunks where spline knots will be placed.
    edges: array of float
      A list of wavelengths giving the edges of chunks where a spline
      knot will be fitted. If this is given, the 'kind' keyword is
      ignored.
    ax : matplotlib Axes
      If this is not None, use ax to make diagnostic plots.

    Additional keywords for kind = 'QSO':

    redshift: float
      QSO emission redshift.
    forest_divmult: float
      Multiplier for the number of spline knots at wavelengths shorter
      than Lya. The default (2) is suitable for UVES/HIRES resoluion
      spectra - experiment with smaller values for lower resolution
      spectra.
    divmult: float
      Multiplier for the number of knots at wavelengths longer than
      Lya.

    Returns
    -------
    co, contpoints: array of shape (N,) and a list of (x,y) pairs.

      co is an estimate for the continuum.

      contpoints is a list of (x,y) pairs, giving the position of
      spline knots used to generate the continuum. Use
      linetools.analysis.interp.AkimaSpline to re-generate the
      continuum from these knots.
    """

    s = np.rec.fromarrays([spec.dispersion.value,
                           spec.flux.value,
                           spec.sig], names=str('wa,fl,er'))

    if edges is not None:
        edges = list(edges)
    elif kind.upper() == 'QSO':
        if 'redshift' in kwargs:
            z = kwargs['redshift']
        elif 'redshift' in spec.meta:
            z = spec.meta['redshift']
        else:
            raise RuntimeError(
                "I need the emission redshift for kind='qso'")

        divmult = kwargs.get('divmult', 2)
        forest_divmult = kwargs.get('forest_divmult', 2)
        edges = make_chunks_qso(
            s.wa, z, debug=debug, divmult=divmult,
            forest_divmult=forest_divmult)
    else:
        s = "Kind keyword {:s} unknown. ".format(kind)
        s += "Currently only kind='QSO' is supported"
        raise ValueError(s)


    if ax is not None:
        ax.plot(s.wa, s.fl, '-', color='0.7', drawstyle='steps-mid')
        ax.plot(s.wa, s.er, 'g')

    knots, indices, masked = prepare_knots(s.wa, s.fl, s.er, edges,
                                           ax=ax, debug=debug)

    # Note this modifies knots and masked inplace
    co = estimate_continuum(s, knots, indices, masked, ax=ax, debug=debug)

    if ax is not None:
        ax.plot(s.wa[~masked], s.fl[~masked], '.y')
        ymax = np.percentile(s.fl[~np.isnan(s.fl)],  95)
        ax.set_ylim(-0.02*ymax, 1.1*ymax)

    return co, [k[:2] for k in knots]
