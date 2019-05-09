# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd
import astropy.io.fits as fits
from astropy.table import Table
from astropy.coordinates import SkyCoord
from astropy import units as u
from astropy.nddata import NDData
from astroimtools import nddata_stats
import datetime
import os
import logging
import time
import seaborn as sns
import matplotlib
import glob
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import copy
from scipy.interpolate import UnivariateSpline as spln

from des_stacks import des_stack as stack
from des_stacks.utils.stack_tools import make_cap_stamps, resample_chip_for_cap, get_chip_vals, get_cuts
from des_stacks.utils.sex_tools import cap_sex_sn, cap_sex_chip, get_sn_dat
from des_stacks.utils.gen_tools import mc_robust_median as r_median

sns.set_palette('Dark2')
sns.set_color_codes(palette='colorblind')
hashes = "#" *45
def init_calib(s,chip,sexcat,phot_type='AUTO'):
    '''Load in the existing DES and the newly SExtracted catalogs'''
    logger = logging.getLogger(__name__)
    logger.handlers =[]
    ch = logging.StreamHandler()
    '''if zp_cut>0:
        logger.setLevel(logging.DEBUG)
        ch.setLevel(logging.DEBUG)
    else:'''
    logger.setLevel(logging.INFO)
    ch.setLevel(logging.INFO)
    formatter =logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    logger.info(hashes)
    logger.info("Entered init_calib to match objects in MY%s, %s, %s, %s, find the zeropoint, \n and give them magnitudes" %(s.my,s.field,chip,s.band))
    logger.info(hashes)
    logger.info("Reading in catalog in order to do photometry")
    cmap = {'PSF':'red','AUTO':'green','cat':'blue','APER':'purple'}
    y3a1_fn = os.path.join(s.cat_dir,'y3a1_%s_%s.csv'%(s.field[3],s.band))
    y3a1 = pd.DataFrame.from_csv(y3a1_fn)
    logger.info("Reading in sexcat: %s"%sexcat)
    sexdat = fits.getdata(sexcat,ext=1)
    logger.info("Successfully read in catalog: %s" %y3a1_fn)
    Band = s.band.capitalize()
    star_inds = ((((y3a1['SPREAD_MODEL_%s'%Band] + 3*y3a1['SPREADERR_MODEL_%s'%Band])<0.003)) & ((y3a1['MAG_AUTO_%s'%Band]>19.5)&(y3a1['MAG_AUTO_%s'%Band]<23.5)))

    y3a1_stars = y3a1[star_inds]

    logger.info("Matching objects...")
    new =pd.DataFrame(sexdat)
    new_obj = SkyCoord(ra=new['X_WORLD'].values*u.degree,dec =new['Y_WORLD'].values*u.degree)
    old_obj = SkyCoord(ra=y3a1_stars['RA'].values*u.degree,dec =y3a1_stars['DEC'].values*u.degree)
    # match the catalogs
    idx, d2d, d3d = new_obj.match_to_catalog_sky(old_obj)
    match_ids = idx
    match_dists = d2d.arcsec
    logger.info("Successfully matched %s objects!" %len(match_ids))
    # get old cat mags of the matched objects
    init_match_cat_mag =y3a1_stars['MAG_AUTO_%s'%Band].iloc[match_ids]
    init_match_cat_magerr =y3a1_stars['MAGERR_AUTO_%s'%Band].iloc[match_ids]
    # get indices of the objects that are within a specified distance of their matches
    dist_cut =2.0
    good_inds = np.nonzero(match_dists < dist_cut)[0]

    good_new_ra = new['X_WORLD'].iloc[good_inds]
    good_new_dec = new['Y_WORLD'].iloc[good_inds]
    logger.info("Using catalog magnitudes to calibrate photometry and get zeropoint")
    # find the new mags that correspond to that
    good_new_mag = new['MAG_AUTO'].iloc[good_inds]
    good_new_magerr = new['MAGERR_AUTO'].iloc[good_inds]
    # and the old ones
    good_cat_mag = init_match_cat_mag.iloc[good_inds]
    good_cat_magerr = init_match_cat_magerr.iloc[good_inds]
    # subtract to get the frame ZP
    diffs = good_cat_mag.values - good_new_mag.values
    zp,zp_sig = r_median(diffs,return_sigma=True)
    psf,psf_sig = r_median(new['FWHM_WORLD']*3600,return_sigma=True)
    logger.info("Successfully calbirated this DES stack of: %s, MY %s, %s band, CCD %s" %(s.field,s.my,s.band,chip))
    logger.info(hashes)
    return zp,zp_sig,psf,psf_sig

def init_phot(s,chip,cat,pl='n'):
    s.logger.info(hashes)
    s.logger.info("Entered 'init_phot.py' to get Kron and PSF photometry, provide limiting magnitudes, and write out the results file for \n MY%s, %s, %s, %s" %(s.my,s.field,chip,s.band))
    s.logger.info(hashes)
    ana_dir = os.path.join(s.band_dir,chip,'ana')
    try:
        final = s.final
    except AttributeError:
        final = True
    # first, get the raw magnitudes and add zero-points to make them proper magnitudes

    if not s.cuts:

        if final ==True:
            imgname = os.path.join(s.band_dir,'ccd_%s_clipweighted_sci.fits'%chip)
        else:
            imgname = s.band_dir+'/ccd_%s_temp.fits'%chip


    else:
        if final ==True:
            imgname = os.path.join(s.band_dir,'ccd_%s_%s_%s_clipweighted_sci.fits'%(chip,s.band,s.cutstring))
        else:
            imgname = s.band_dir+'/ccd_%s_%s_%s_temp.fits'%(chip,s.band,s.cutstring)
    cuts = imgname.split('_')
    quals= np.loadtxt(os.path.join(ana_dir,'%s_ana.qual'%s.cutstring))
    zp = float(quals[0])
    zp_sig = float(quals[1])
    av_fwhm = float(quals[2])
    cat = cat.sort_values(by='X_WORLD')
    cat['MAG_AUTO']=cat['MAG_AUTO']+zp
    try:
        cat['MAG_APER']=cat['MAG_APER']+zp
    except:
        s.logger.info('Aperture photometry appears not to have been done yet; consider doing it')
    # get rid of clearly wrong values
    truth =cat['MAG_AUTO']<35
    cat = cat.iloc[truth.values]

    # make region files for ds9
    krreg = open(os.path.join(ana_dir,'%s_%s_%s_%s_auto.reg'%(s.my,s.field,s.band,chip)),'w')

    for i in range(len(cat['X_WORLD'].values)):
        print ('fk5; circle(%s,%s,1") # text={%.2f +/- %.2f}'%(cat['X_WORLD'].iloc[i],cat['Y_WORLD'].iloc[i],cat['MAG_AUTO'].iloc[i],cat['MAGERR_AUTO'].iloc[i]),file=krreg)
    krreg.close()
    s.logger.info("Saved ds9 region files in /ana directory")
    sns.set_palette('Dark2')
    sns.set_color_codes(palette='colorblind')
    if pl == 'y':
        f,ax=plt.subplots()
        alp= 0.75
        cat.hist(column='MAG_AUTO',bins=150,normed=True,ax=ax,alpha=alp+0.25,label='Kron Magnitudes',color='r')

        ax.set_xlabel('Mag')
        ax.set_ylabel('Frequency Density')
        ax.set_title('Magnitude Distribution in MY %s, %s, CCD %s, %s' %(s.my,s.field,chip,s.band))
    #ax.set_yscale('log')
    hst,bin_edges = np.histogram(cat['MAG_AUTO'],bins=150,density=True)

    splkron = spln(bin_edges[1:],hst,s=0.02)

    x2 = np.linspace(bin_edges[0],bin_edges[-1],200)
    y2= splkron(x2)

    kr_lim = x2[np.argmax(y2)]

    limsig = 10
    errthresh = 2.5*np.log10(1+(1/limsig))
    if pl == 'y':
        ax.plot(x2,y2,c='r')
        ax.set_xlim(17,30)
        ax.vlines(kr_lim,0,1.1*np.max(y2),linestyle='--',label='Limiting Kron magnitude',color='r')
        ax.legend()
        f.savefig(os.path.join(ana_dir,'%s_%s_%s_%s_hist.jpg'%(s.my,s.field,s.band,chip)))
        f2,ax2 = plt.subplots()
        cat.plot.scatter('MAG_AUTO','MAGERR_AUTO',s=5,ax=ax2,label='Kron Magnitudes',color='r')
        ax2.set_xlabel('Magnitude')
        ax2.set_ylabel('Magnitude Error')
        ax2.hlines(errthresh,15,30,linestyle='--',color='#7570b3')
        ax2.set_xlim(17,30)
        ax2.set_ylim(-0.03,0.35)
        ax2.legend()
        f2.savefig(os.path.join(ana_dir,'%s_%s_%s_%s_mag_vs_err.jpg'%(s.my,s.field,s.band,chip)))
        plt.close('all')
    b_hi = errthresh +(errthresh/500)
    b_lo = errthresh -(errthresh/500)
    c2 = cat[cat['MAGERR_AUTO']<b_hi]
    c2 = c2[c2['MAGERR_AUTO']>b_lo]
    kr_lim2 = c2['MAG_AUTO'].median()

    nclip=50
    s.logger.info("Running nddata_stats on %s in order to get sky noise" %imgname)
    nd1 = NDData(fits.getdata(imgname))
    columns=['mean','std']
    tbl = nddata_stats(nd1,columns=columns,sigma=2.8,iters=10)
    s.logger.info(tbl)
    mean,skynoise = tbl['mean'],tbl['std']
    s.logger.info('Skynoise: %s'%skynoise)
    h = fits.getheader(imgname)
    exptime= h['EXPTIME']
    pixscale=0.27

    thresh = 5
    skyflux = skynoise*np.sqrt(np.pi*(av_fwhm/pixscale)**2)
    skymag = 2.5*np.log10(thresh*skyflux)
    skylim = zp -skymag
    s.logger.info("Limiting Kron magnitude based on matched objects: %.3f\n"% kr_lim)
    s.logger.info("%s sigma limiting magnitude based on matched objects: %.3f\n"%(limsig,kr_lim2))
    s.logger.info("%s sigma limiting magnitude using zeropoint %.3f: %.3f\n "%(thresh,zp,skylim))

    resfile = open(os.path.join(ana_dir,'%s_%s_%s_%s_init_wgtd.result'%(s.my,s.field,s.band,chip)),'w')
    cat['FWHM_WORLD'] = cat['FWHM_WORLD']*3600
    for i in range(len(cat['FWHM_WORLD'].values)):
        cat['FWHM_WORLD'].values[i] = float(cat['FWHM_WORLD'].values[i])
    radec=cat[['X_WORLD','Y_WORLD']].applymap("{0:7.5f}".format)
    try:
        rest = cat[['MAG_AUTO','MAGERR_AUTO','MAG_PSF','MAGERR_PSF','MAG_APER','MAGERR_APER','FWHM_WORLD','ELONGATION']].applymap("{0:4.3f}".format)
    except:
        rest = cat[['MAG_AUTO','MAGERR_AUTO','MAG_PSF','MAGERR_PSF','FWHM_WORLD','ELONGATION']].applymap("{0:4.3f}".format)

    rest[['X_WORLD','Y_WORLD']]=radec[['X_WORLD','Y_WORLD']]
    rest['CLASS_STAR']=cat['CLASS_STAR']
    rest['FLUX_RADIUS']=cat['FLUX_RADIUS']
    cols = rest.columns.tolist()
    rearranged = cols[-2:]+cols[:-2]
    re = rest[rearranged]
    re.to_csv(os.path.join(s.temp_dir,'temp_cat.csv'),index=False,sep=' ')
    stringthing = open(os.path.join(s.temp_dir,'temp_cat.csv'),'r')
    psfstring = stringthing.read()
    stringthing.close()
    reshead = '# Result file for a stack of Dark Energy Survey data taken by DECam\n'
    reshead +='# Field: %s\n'% s.field
    reshead +='# Minus year: %s\n'% s.my
    reshead +='# Band: %s\n' % s.band
    reshead +='# CCD Number: %s\n' % chip
    reshead +='# Total exposure time: %s s\n' %exptime
    reshead +='# Zeropoint based on AUTO photometry: %s \n'%zp
    reshead +='# 1 sigma error on the zeropoint: %s \n'%zp_sig
    reshead +='# Limiting Kron magnitude based on matched objects: %.3f\n'% kr_lim
    reshead +='# %s sigma limiting magnitude based on matched objects: %.3f\n'%(limsig,kr_lim2)
    reshead +='# %s sigma limiting magnitude using zeropoint %.3f: %.3f\n' %(thresh,zp,skylim)
    reshead +='# Columns:\n'
    reshead +='# Dec (J2000)\n'
    reshead +='# Kron Magnitude\n'
    reshead +='# Kron Magnitude error\n'
    reshead +='# PSF Magnitude\n'
    reshead +='# PSF Magnitude error\n'
    reshead +='# FWHM of the source (arcsec)\n'
    reshead +='# Elongation of source\n'
    reshead +='# Flux Radius\n'
    resfile.write(reshead)
    resfile.write(psfstring)
    savestring = os.path.join(ana_dir,'%s_%s_%s_%s_init.result'%(s.my,s.field,s.band,chip))
    s.logger.info("Saved result file to: %s"%savestring)
    s.logger.info(hashes)
    return (kr_lim,kr_lim2,skylim,np.mean([kr_lim,kr_lim2,skylim]))

#####################################################################################################
def cap_phot_sn(sn_name,wd = 'coadding',savename = 'all_sn_phot.csv',dist_thresh = 5,autocuts=False,new=True):
    '''get aperture photometry for a single sn host'''
    logger = logging.getLogger(__name__)
    logger.handlers =[]
    ch = logging.StreamHandler()
    '''if zp_cut>0:
        logger.setLevel(logging.DEBUG)
        ch.setLevel(logging.DEBUG)
    else:'''
    logger.setLevel(logging.DEBUG)
    ch.setLevel(logging.DEBUG)
    formatter =logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    logger.info("Entered 'cap_phot.py' to do common aperture photometry for the host of %s"%sn_name)
    logger.info("Will search a radius of %s arcseconds around the SN location"%dist_thresh)
    # first let's get to the right directory and set up a stack class object for each band_dir
    bands = ['g','r','i','z']

    ra,dec,f,y,chip = get_sn_dat(sn_name)
    if not new:
        if y ==5:
            y='none'
    logger.info("Found transient in the database SNCAND")
    logger.info("It's in %s, in Season %s, on chip %s, at coordinates RA = %s, Dec = %s"%(f,y,chip,ra,dec))
    # Make a Stack instance for each band
    logger.info("Setting up Stack instances for each band")
    if autocuts:
        cuts = [get_cuts(f,b) for b in bands]
    else:
        cuts = [{'teff': 0.15, 'psf':None},{'teff': 0.15,'psf':None},{'teff': 0.25,'psf':None},{'teff': 0.25,'psf':None}]
    sg,sr,si,sz = [stack.Stack(f, b, y, chip ,wd,cuts[counter],new=new) for counter,b in enumerate(bands)]

    # if there is no white image, make ones
    det_name = os.path.join(sg.out_dir,'CAP',sn_name,'%s_white_stamp.fits'%(sn_name))
    if not os.path.isfile(det_name):
        logger.info("Couldn't find a detection image, so going to make 300x300 pix stamps of each band plus white")
        det_name = make_cap_stamps(sg,sr,si,sz,chip,sn_name,ra,dec,300,300)
    # check to see if sexcats exist already
    existing_sexcats = glob.glob(os.path.join(sg.out_dir,'CAP',sn_name,'*.sexcat'))

    sexcats = {}
    '''for b in bands:
        sexcat_fn = '%s_%s_cap_sci.sexcat'%(sn_name,b)
        sexcat_path = os.path.join(sg.out_dir,'CAP',sn_name)
        full_sexcat_fn = os.path.join(sexcat_path,sexcat_fn)
        if full_sexcat_fn in existing_sexcats:
            sexcats[b]=os.path.join(sg.out_dir,'CAP',sn_name,full_sexcat_fn)
    if len(existing_sexcats)!=4:'''

        # do common aperture photometry
    logger.info("Going to cap_sex to do CAP on each band")

    sexcats =cap_sex_sn(sg,sr,si,sz,chip,sn_name)
    # set up an empty results dataframe
    rescols = ['SN_NAME','X_WORLD', 'Y_WORLD','X_IMAGE','Y_IMAGE',
               'A_IMAGE','B_IMAGE','THETA_IMAGE','CXX_IMAGE','CYY_IMAGE','CXY_IMAGE',
                           'MAG_AUTO_g', 'MAGERR_AUTO_g','MAG_APER_g', 'MAGERR_APER_g',
                           'MAG_AUTO_r', 'MAGERR_AUTO_r','MAG_APER_r', 'MAGERR_APER_r',
                           'MAG_AUTO_i', 'MAGERR_AUTO_i','MAG_APER_i', 'MAGERR_APER_i',
                           'MAG_AUTO_z', 'MAGERR_AUTO_z','MAG_APER_z', 'MAGERR_APER_z',
                           'FWHM_WORLD_g','FWHM_WORLD_r','FWHM_WORLD_i','FWHM_WORLD_z',
                           'ELONGATION',
                           'KRON_RADIUS',
                           'CLASS_STAR_g','CLASS_STAR_r','CLASS_STAR_i','CLASS_STAR_z',
                           'LIMMAG_g','LIMMAG_r','LIMMAG_i','LIMMAG_z',
                           'FLUX_RADIUS_g','FLUX_RADIUS_r','FLUX_RADIUS_i','FLUX_RADIUS_z',
                           'DLR',
                           'DLR_RANK']
    res_df = pd.DataFrame(columns=rescols)
    for s in [sg,sr,si,sz]:
        # load in the photometry from sextractor

        if autocuts:
            quals= np.loadtxt(os.path.join(s.band_dir,str(chip),'ana','%s_ana.qual'%s.cutstring))
        else:
            qualfiles = glob.glob(os.path.join(s.band_dir,str(chip),'ana','*_ana.qual'))
            quals =np.loadtxt(qualfiles[-1])
        zp = float(quals[0])
        av_fwhm = float(quals[2])
        capcat_fn = os.path.join(sg.out_dir,'CAP',sn_name,'%s_%s_cap_sci.sexcat'%(sn_name,s.band))
        logger.info('Reading in the catalog from: %s'%capcat_fn)
        capcat = Table.read(capcat_fn).to_pandas()
        capcat['MAG_APER']=capcat['MAG_APER']+zp
        capcat['MAG_AUTO']=capcat['MAG_AUTO']+zp

        sncoord = SkyCoord(ra = ra*u.deg,dec = dec*u.deg)
        catalog = SkyCoord(ra = capcat.X_WORLD.values*u.deg,dec = capcat.Y_WORLD.values*u.deg)
        d2d= sncoord.separation(catalog)
        close_inds = d2d <dist_thresh*u.arcsec
        dists = d2d[close_inds]
        match = capcat.iloc[close_inds]
        angsep = np.array([float(d2d[close_inds][j].to_string(unit=u.arcsec,decimal=True)) for j in range(len(d2d[close_inds]))])
        with open(os.path.join(s.band_dir,str(chip),'ana',
            '%s_%s_%s_%s_init.result'%(y,f,s.band,chip)),'r') as resheader:
            header = [next(resheader) for x in range(9)]
        limmag = header[-1].split(' ')[-1].strip('\n')
        logger.info("Found %s galaxies within %s arcseconds in %s band"%(len(match),dist_thresh,s.band))
        if len(match)==0:

            logger.info("Didn't detect a galaxy within 2 arcsec of the SN; reporting limit of %s in %s band"%(limmag,s.band))

            init_lim_array = np.array([sn_name,ra,dec,limmag,-1,limmag,-1,-1,-1,-1,-1,limmag,-1,-1])
            init_lim_cols = [
            'MAG_AUTO_%s'%s.band, 'MAGERR_AUTO_%s'%s.band,
            'MAG_APER_%s'%s.band, 'MAGERR_APER_%s'%s.band,
            'CLASS_STAR_%s'%s.band,
            'LIMMAG_%s'%s.band,
            ]
            if s.band =='g':
                res_df=pd.DataFrame([init_lim_array],
                columns=init_lim_cols)
            else:

                lim_cols = [
                'MAG_AUTO_%s'%s.band, 'MAGERR_AUTO_%s'%s.band,
                'MAG_APER_%s'%s.band, 'MAGERR_APER_%s'%s.band,
                'CLASS_STAR_%s'%s.band,
                'LIMMAG_%s'%s.band,
                ]
                lim_array = np.array([limmag,-1,limmag,-1,-1,-1,-1,-1,limmag,-1,-1])
                for counter,c in enumerate(lim_cols):
                    res_df[c] = ''

                    res_df[c].iloc[0] = lim_array[counter]
        else:
            #match.index = ['%s_%s'%(sn_name,i) for i in range(len(match.index))]

            band_col_keys = ['MAG_AUTO', 'MAGERR_AUTO', 'MAG_APER', 'MAGERR_APER','CLASS_STAR']
            band_cols = {}
            new_band_cols = []
            for col in band_col_keys:
                band_cols[col]=col+'_%s'%s.band
                new_band_cols.append(col+'_%s'%s.band)
            if s.band =='g':
                match =match.rename(index=str,columns=band_cols)

                res_df = res_df.append(match)
                res_df['SN_NAME']=sn_name
                dlr = get_DLR_ABT(ra,dec, match.X_WORLD, match.Y_WORLD, match['A_IMAGE'], match['B_IMAGE'],  match['THETA_IMAGE'], angsep)[0]

                res_df['DLR'] = np.array(dlr)
                rank = res_df['DLR'].rank().astype(int)
                for counter, r in enumerate(res_df['DLR'].values):
                    if r >4:
                        rank[counter]*=-1
                res_df['DLR_RANK']=rank
            else:
                match =match.rename(index=str,columns=band_cols)

                match = match[new_band_cols]
                for c in match.columns:
                    res_df[c]= match[c]
            res_df['LIMMAG_%s'%s.band]= limmag
            res_df = res_df[res_df['DLR']<10]
            # make region files for ds9
            reg = open(os.path.join(s.out_dir,'CAP',sn_name,'%s_%s.reg'%(sn_name,s.band)),'w')

            for i in range(len(capcat['X_WORLD'].values)):
                print ('fk5; circle(%s,%s,1") # text={%.2f +/- %.2f}'%(capcat['X_WORLD'].iloc[i],capcat['Y_WORLD'].iloc[i],capcat['MAG_AUTO'].iloc[i],capcat['MAGERR_AUTO'].iloc[i]),file=reg)
            print ('fk5; point %s %s # point=cross text={%s} color=red'%(ra,dec,sn_name),file=reg)
            reg.close()
    for col in ['z','z_Err','flag','source']:
        res_df[col] = ''
    if len(match)>0:
        nearby_grc,grc_coords = get_zs_box(sg,ra,dec,30)

        gal_coords = SkyCoord(ra=res_df['X_WORLD'].values*u.deg,dec=res_df['Y_WORLD'].values*u.deg)
        logger.info('Attempting to add some redshift infomation')

        res_df = match_gals(grc_coords,gal_coords,nearby_grc,res_df)


    all_sn_fn = os.path.join(sg.res_dir,savename)
    if os.path.isfile(all_sn_fn):
        all_sn = pd.read_csv(all_sn_fn,index_col=0)
    else:
        all_sn = pd.DataFrame(columns = rescols)
    all_sn = all_sn.append(res_df.reset_index(drop=True)).reset_index(drop=True)
    print ('Saving result to %s'%all_sn_fn)
    all_sn.to_csv(all_sn_fn)

    logger.info("Done doing CAP for %s"%sn_name)
    return res_df

def cap_phot_all(y,f,chip,wd='coadding',autocuts = False):
    '''get aperture photometry for an entire chip'''
    logger = logging.getLogger(__name__)
    logger.handlers =[]
    ch = logging.StreamHandler()
    logger.setLevel(logging.DEBUG)
    ch.setLevel(logging.DEBUG)
    formatter =logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    logger.info(hashes)
    logger.info("Entered 'cap_phot_all' to do common aperture photometry for MY%s, %s, chip %s"%(y,f,chip))
    logger.info(hashes)
    # first let's get to the right directory and set up a stack class object for each band_dir
    bands = ['g','r','i','z']
    if autocuts:
        cuts = [get_cuts(f,b) for b in bands]
    else:
        cuts = [{'teff': 0.15, 'psf':2.2},{'teff': 0.2,'psf':2.2},{'teff': 0.24,'psf':2.4},{'teff': 0.4,'psf':2.6}]
    sg,sr,si,sz = [stack.Stack(f, b, y, [str(chip)] ,wd,cuts[counter]) for counter,b in enumerate(bands)]
    for counter,s in enumerate([sg,sr,si,sz]):
        s.cuts = cuts[counter]
    # if there is no white image, make one
    det_name = os.path.join(sg.out_dir,'MY%s'%y,f,'CAP',str(chip),'%s_%s_%s_riz.fits'%(y,f,chip))
    if not os.path.isfile(det_name):
        logger.info("Couldn't find a detection image, so going to resample each band plus a riz combo to the same pixels")
        noff1,noff2 = 0,0
        while True:
            det_name,noff1,noff2 = resample_chip_for_cap(sg,sr,si,sz,chip,npix_off1=noff1,npix_off2 = noff2)
            if noff1 == 0 and noff2 == 0:
                break

    # do common aperture photometry
    logger.info("Going to cap_sex to do CAP on each band")
    sexcats =cap_sex_chip(sg,sr,si,sz,chip)
    '''for s in [sg,sr,si,sz]:
        sexcat = sexcats[s.band]
        zp,zp_sig,sex_fwhm,sex_fwhm_sig = init_calib(s,chip,sexcat)
        qual = np.array([zp,zp_sig,sex_fwhm,sex_fwhm_sig])
        qual_fn = os.path.join(s.band_dir,str(chip),'ana','%s_ana.qual'%s.cutstring)
        np.savetxt(qual_fn,qual)'''
    # set up an empty results dataframe
    rescols= ['X_WORLD', 'Y_WORLD','X_IMAGE','Y_IMAGE',
               'A_IMAGE','B_IMAGE','THETA_IMAGE','CXX_IMAGE','CYY_IMAGE','CXY_IMAGE',
                           'MAG_AUTO_g', 'MAGERR_AUTO_g','MAG_APER_g', 'MAGERR_APER_g',
                           'MAG_AUTO_r', 'MAGERR_AUTO_r','MAG_APER_r', 'MAGERR_APER_r',
                           'MAG_AUTO_i', 'MAGERR_AUTO_i','MAG_APER_i', 'MAGERR_APER_i',
                           'MAG_AUTO_z', 'MAGERR_AUTO_z','MAG_APER_z', 'MAGERR_APER_z',
                           'FLUX_AUTO_g', 'FLUXERR_AUTO_g','FLUX_APER_g', 'FLUXERR_APER_g',
                           'FLUX_AUTO_r', 'FLUXERR_AUTO_r','FLUX_APER_r', 'FLUXERR_APER_r',
                           'FLUX_AUTO_i', 'FLUXERR_AUTO_i','FLUX_APER_i', 'FLUXERR_APER_i',
                           'FLUX_AUTO_z', 'FLUXERR_AUTO_z','FLUX_APER_z', 'FLUXERR_APER_z',
                           'FWHM_WORLD_g','FWHM_WORLD_r','FWHM_WORLD_i','FWHM_WORLD_z',
                           'ELONGATION',
                           'KRON_RADIUS',
                           'MY',
                           'FIELD'
                           'CCDNUM',
                           'PHOTOZ','PHOTOZ_ERR',
                           'CLASS_STAR_g','CLASS_STAR_r','CLASS_STAR_i','CLASS_STAR_z',
                           'LIMMAG_g','LIMMAG_r','LIMMAG_i','LIMMAG_z',
                           'LIMFLUX_g','LIMFLUX_r','LIMFLUX_i','LIMFLUX_z',
                           'FLUX_RADIUS_g','FLUX_RADIUS_r','FLUX_RADIUS_i','FLUX_RADIUS_z']

    res_df = pd.DataFrame(columns=rescols)
    this_chip_lims = get_chip_vals(sg.field,chip,vals = 'lims')
    chip_cent_ra = (this_chip_lims[0][0]+this_chip_lims[2][0])/2
    chip_cent_dec = (this_chip_lims[0][1]+this_chip_lims[1][1])/2
    chip_search_rad = np.abs(this_chip_lims[1][1]-this_chip_lims[0][1])
    logger.debug('Searching for galaxy redshifts around %s, %s, %s' %(chip_cent_ra,chip_cent_dec,chip_search_rad))
    gals_with_z,gals_with_z_coords = get_zs_box(sg,chip_cent_ra,chip_cent_dec,chip_search_rad)
    # find the galaxies that OzDES has redshifts for
    cats, limmags, limfluxes = {},{},{}
    for counter,s in enumerate([sg,sr,si,sz]):
        # load in the photometry from sextractor
        s.cuts = cuts[counter]
        logger.info('Loading in sexcat with name: %s',sexcats[s.band])
        capcat = Table.read(sexcats[s.band]).to_pandas()
        quals= np.loadtxt(os.path.join(s.band_dir,str(chip),'ana','%s_ana.qual'%s.cutstring))
        if len(quals)!=4:
            s.run_stack_sex(cuts=cuts[counter],final=True)
            quals= np.loadtxt(os.path.join(s.band_dir,str(chip),'ana','%s_ana.qual'%s.cutstring))

        zp,zp_sig,av_fwhm = (float(quals[i]) for i in [0,1,2])
        logger.info('Reading in zeropoint from %s' %os.path.join(s.band_dir,str(chip),'ana','%s_ana.qual'%s.cutstring))

        capcat = capcat.sort_values(by='X_WORLD')
        logger.info("Calibrating in %s band using zeropoint from result file: %.3f"%(s.band,zp))

        # get rid of clearly wrong values
        truth =capcat['MAG_AUTO']<35
        capcat = capcat.iloc[truth.values]
        capcat['MAGERR_SYST_AUTO'] = zp_sig
        capcat['MAGERR_SYST_APER'] = zp_sig
        capcat['MAGERR_STATSYST_AUTO'] = (zp_sig**2 + capcat['MAGERR_AUTO'].values**2)**0.5
        capcat['MAGERR_STATSYST_APER'] = (zp_sig**2 + capcat['MAGERR_APER'].values**2)**0.5
        auto_lower_than_inds = capcat['MAGERR_STATSYST_AUTO']<zp_sig
        capcat['MAGERR_STATSYST_AUTO'][auto_lower_than_inds]=zp_sig
        aper_lower_than_inds = capcat['MAGERR_STATSYST_APER']<zp_sig
        capcat['MAGERR_STATSYST_APER'][aper_lower_than_inds]=zp_sig
        capcat['MAG_ZEROPOINT'] = zp
        capcat['MAG_ZEROPOINT_ERR'] = zp_sig
        capcat['CCDNUM'] = chip
        capcat['FIELD'] = f
        capcat['MY'] = y
        capcat['PHOTOZ'],capcat['PHOTOZ_ERR']= '',''
        if not os.path.isfile(os.path.join(s.band_dir,str(chip),'ana','%s_%s_%s_%s_init_wgtd.result'%(y,f,s.band,chip))):
            s.sexcats = [os.path.join(s.band_dir,str(chip),'ana','MY%s_%s_%s_%s_%s_clipweighted_sci.sexcat'%(y,f,s.band,chip,s.cutstring))]
            s.init_phot()
        with open(os.path.join(s.band_dir,str(chip),'ana','%s_%s_%s_%s_init_wgtd.result'%(y,f,s.band,chip)),'r') as res:
                header = [next(res) for x in range(9)]
        limmag = header[-1].split(' ')[-1].strip('\n')
        limflux = 10**((float(limmag)-zp)/-2.5)
        capcat['LIMMAG'] = limmag
        capcat['LIMFLUX'] = limflux
        cats[s.band] = capcat
        limmags[s.band] = limmag
        limfluxes[s.band] = limflux

    main_cat_df = cats['g']
    for counter, b in enumerate(bands[:3]):
        main_cat_df = main_cat_df.merge(cats[bands[counter+1]],left_index=True,right_index=True,how='outer',
        on=['X_WORLD','Y_WORLD',
        'X_IMAGE','Y_IMAGE',
        'KRON_RADIUS','ELONGATION',
        'A_IMAGE','B_IMAGE',
        'THETA_IMAGE','CXX_IMAGE','CYY_IMAGE','CXY_IMAGE',
        'MY',
        'FIELD',
        'CCDNUM',
        'PHOTOZ','PHOTOZ_ERR'],suffixes=('_%s'%b,'_%s'%bands[counter+1]))
    for b in bands:
        logger.info('Filling nanas in %s band with %s'%(b,limmags[b]))
        main_cat_df['MAG_AUTO_%s'%b].fillna(limmags[b],inplace=True)
        main_cat_df['MAG_APER_%s'%b].fillna(limmags[b],inplace=True)
        main_cat_df['MAGERR_AUTO_%s'%b].fillna(-9999,inplace=True)
        main_cat_df['MAGERR_APER_%s'%b].fillna(-9999,inplace=True)
        main_cat_df['FLUX_AUTO_%s'%b].fillna(limfluxes[b],inplace=True)
        main_cat_df['FLUX_APER_%s'%b].fillna(limfluxes[b],inplace=True)
        main_cat_df['FLUXERR_AUTO_%s'%b].fillna(-9999,inplace=True)
        main_cat_df['FLUXERR_APER_%s'%b].fillna(-9999,inplace=True)
    catobjs = SkyCoord(ra = main_cat_df['X_WORLD'].values*u.degree,dec = main_cat_df['Y_WORLD'].values*u.degree)
    # match the cap catalog with the ozdes one
    logger.debug('Len of grccoord,capcoord for chip %s: %s, %s'%(chip,len(gals_with_z_coords),len(catobjs)))
    matched_cat_df = match_gals(gals_with_z_coords,catobjs,gals_with_z,main_cat_df,dist_thresh=1.5)
    logger.debug(matched_cat_df.columns)
    low_conf_z = matched_cat_df[(matched_cat_df['source']=='DES_AAOmega')&((matched_cat_df['flag']=='1')|(matched_cat_df['flag']=='2'))]
    logger.info('Found these OzDES targets with z flag 1 or 2: ')
    logger.info(low_conf_z[['z','source','flag']])
    matched_cat_df['z'].loc[low_conf_z.index] = -9.9900
    matched_cat_df['z_Err'].loc[low_conf_z.index] = -9999

    matched_cat_df.to_csv(os.path.join(sg.out_dir,'MY%s'%y,f,'CAP',str(chip),'%s_%s_%s_obj_deep.cat'%(sg.my,sg.field,chip)))
    logger.info("Done CAP on %s, MY%s, CCD %s. Saved result to %s "%(f,y,chip,os.path.join(sg.out_dir,'MY%s'%y,f,'CAP',str(chip),'%s_%s_%s_obj_deep.cat'%(sg.my,sg.field,chip))))

    logger.info(hashes)
    return matched_cat_df

def cap_sn_lookup(sn_name,wd = 'coadding',savename = 'all_sn_phot.csv',dist_thresh = 5,autocuts=False):
    '''get aperture photometry for a single sn host'''
    logger = logging.getLogger(__name__)
    logger.handlers =[]
    ch = logging.StreamHandler()
    '''if zp_cut>0:
        logger.setLevel(logging.DEBUG)
        ch.setLevel(logging.DEBUG)
    else:'''
    logger.setLevel(logging.DEBUG)
    ch.setLevel(logging.DEBUG)
    formatter =logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    logger.info("Entered 'cap_phot.py' to do common aperture photometry for the host of %s"%sn_name)
    logger.info("Will search a radius of %s arcseconds around the SN location"%dist_thresh)
    # first let's get to the right directory and set up a stack class object for each band_dir
    bands = ['g','r','i','z']

    try:
        ra,dec,f,y,chip = get_sn_dat(sn_name)
    except:
        return None
    my = 'MY'+str(y)
    logger.info("Found %s in the database SNCAND"%sn_name)
    logger.info("It's in %s, in Season %s, on chip %s, at coordinates RA = %s, Dec = %s"%(f,y,chip,ra,dec))
    # Make a Stack instance for each band

    capres_fn = os.path.join('/media/data3/wiseman/des/coadding/5yr_stacks',my,
                             f,'CAP',str(chip),'%s_%s_%s_obj_deep.cat'%(y,f,chip))
    logger.info('Searching for %s in %s'%(sn_name,capres_fn))
    capres = pd.read_csv(capres_fn,index_col = 0)
    search_rad = dist_thresh
    capres = capres[(capres['X_WORLD']< ra+search_rad)&(capres['X_WORLD']> ra-search_rad) & (capres['Y_WORLD']> dec-search_rad) & (capres['Y_WORLD']< dec+search_rad)]

    cols = capres.columns.tolist() + [
        'SNID',
         'DLR',
         'DLR_RANK',
         'ANGSEP',
         'EDGE_FLAG'
    ]
    res_df = pd.DataFrame(columns=cols)
    res_df['EDGE_FLAG'] = 0
    sncoord = SkyCoord(ra = ra*u.deg,dec = dec*u.deg)
    catalog = SkyCoord(ra = capres.X_WORLD.values*u.deg,dec = capres.Y_WORLD.values*u.deg)
    d2d= sncoord.separation(catalog)
    close_inds = d2d <dist_thresh*u.arcsec
    dists = d2d[close_inds]
    match = capres.iloc[close_inds]
    angsep = np.array([float(d2d[close_inds][j].to_string(unit=u.arcsec,decimal=True)) for j in range(len(d2d[close_inds]))])
    logger.info("Found %s galaxies within %s arcseconds of %s"%(len(match),dist_thresh,sn_name))
    if len(match)==0:

        logger.info("Didn't detect a galaxy within %s arcsec of %s; reporting limits only"%(dist_thresh,sn_name))
        res_df = res_df.append(capres.iloc[0])

        res_df[['X_WORLD', 'Y_WORLD', 'X_IMAGE', 'Y_IMAGE', 'MAG_AUTO_g',
       'MAGERR_AUTO_g', 'MAG_APER_g', 'MAGERR_APER_g', 'FLUX_AUTO_g',
       'FLUXERR_AUTO_g', 'FLUX_APER_g', 'FLUXERR_APER_g', 'FWHM_WORLD_g',
       'ELONGATION', 'KRON_RADIUS', 'CLASS_STAR_g', 'FLUX_RADIUS_g', 'A_IMAGE',
       'B_IMAGE', 'THETA_IMAGE', 'CXX_IMAGE', 'CYY_IMAGE', 'CXY_IMAGE',
       'MAGERR_SYST_AUTO_g', 'MAGERR_SYST_APER_g', 'MAGERR_STATSYST_AUTO_g',
       'MAGERR_STATSYST_APER_g', 'MAG_ZEROPOINT_g', 'MAG_ZEROPOINT_ERR_g',
       'CCDNUM', 'FIELD', 'MY', 'PHOTOZ', 'PHOTOZ_ERR', 'MAG_AUTO_r',
       'MAGERR_AUTO_r', 'MAG_APER_r', 'MAGERR_APER_r', 'FLUX_AUTO_r',
       'FLUXERR_AUTO_r', 'FLUX_APER_r', 'FLUXERR_APER_r', 'FWHM_WORLD_r',
       'CLASS_STAR_r', 'FLUX_RADIUS_r', 'MAGERR_SYST_AUTO_r',
       'MAGERR_SYST_APER_r', 'MAGERR_STATSYST_AUTO_r',
       'MAGERR_STATSYST_APER_r', 'MAG_ZEROPOINT_r', 'MAG_ZEROPOINT_ERR_r',
       'MAG_AUTO_i', 'MAGERR_AUTO_i', 'MAG_APER_i', 'MAGERR_APER_i',
       'FLUX_AUTO_i', 'FLUXERR_AUTO_i', 'FLUX_APER_i', 'FLUXERR_APER_i',
       'FWHM_WORLD_i', 'CLASS_STAR_i', 'FLUX_RADIUS_i', 'MAGERR_SYST_AUTO_i',
       'MAGERR_SYST_APER_i', 'MAGERR_STATSYST_AUTO_i',
       'MAGERR_STATSYST_APER_i', 'MAG_ZEROPOINT_i', 'MAG_ZEROPOINT_ERR_i',
       'MAG_AUTO_z', 'MAGERR_AUTO_z', 'MAG_APER_z', 'MAGERR_APER_z',
       'FLUX_AUTO_z', 'FLUXERR_AUTO_z', 'FLUX_APER_z', 'FLUXERR_APER_z',
       'FWHM_WORLD_z', 'CLASS_STAR_z', 'FLUX_RADIUS_z', 'MAGERR_SYST_AUTO_z',
       'MAGERR_SYST_APER_z', 'MAGERR_STATSYST_AUTO_z',
       'MAGERR_STATSYST_APER_z', 'MAG_ZEROPOINT_z', 'MAG_ZEROPOINT_ERR_z','DLR', 'DLR_RANK',
       'ANGSEP','z','z_Err','flag','source']] = np.NaN
        res_df.SNID = sn_name

    else:

        res_df = res_df.append(match)

        res_df['SNID']=sn_name
        dlr = get_DLR_ABT(ra,dec, match.X_WORLD, match.Y_WORLD, match['A_IMAGE'], match['B_IMAGE'],  match['THETA_IMAGE'], angsep)[0]

        res_df['ANGSEP'] = angsep

        res_df['DLR'] = np.array(dlr)
        rank = res_df['DLR'].rank().astype(int)

        for counter, r in enumerate(res_df['DLR'].values):
            if r >4:
                rank.iloc[counter]*=-1
        res_df['DLR_RANK']=rank
        if len(match)>5:
            res_df = res_df[res_df['DLR']<30]
        logger.info(res_df[res_df['DLR_RANK']==1].index)
        ind = res_df[res_df['DLR_RANK']==1].index
        try:
            if res_df[res_df['DLR_RANK']==1]['z'].values[0]>0:
                pass
            else:
                snspect = pd.read_csv('/media/data3/wiseman/des/coadding/catalogs/snspect.csv')
                snspecobs = snspect[snspect['TRANSIENT_NAME']==sn_name]

                if len (snspecobs)>0:
                    for i in range(len(snspecobs)):
                        if snspecobs['Z_GAL'].values[i]>0:
                            logger.info(snspecobs['Z_GAL'].values[i])
                            try:
                                res_df['z'].loc[ind]=snspecobs['Z_GAL'].values[i]
                                res_df['z_Err'].loc[ind] = -9999.0
                            except:
                                res_df['z'].loc[ind]=snspecobs['Z_GAL']
                                res_df['z_Err'].loc[ind] = -9999.0
        except:
            pass
        res_df['EDGE_FLAG'] = get_edge_flags(res_df.X_IMAGE.values,res_df.Y_IMAGE.values)
    if not os.path.isdir('/media/data3/wiseman/des/coadding/5yr_stacks/CAP/%s'%sn_name):
        os.mkdir('/media/data3/wiseman/des/coadding/5yr_stacks/CAP/%s'%sn_name)
    save_fn = '/media/data3/wiseman/des/coadding/5yr_stacks/CAP/%s/%s.result'%(sn_name,sn_name)
    logger.info('Saving result of %s to %s'%(sn_name,save_fn))
    res_df.to_csv(save_fn)

    logger.info("Done finding CAP for %s"%sn_name)
    return res_df

def get_DLR_ABT(RA_SN, DEC_SN, RA, DEC, A_IMAGE, B_IMAGE, THETA_IMAGE, angsep):
    # inputs are arrays
    rad  = np.pi/180                   # convert deg to rad
    pix_arcsec = 0.264                 # pixel scale (arcsec per pixel)
    pix2_arcsec2 = 0.264**2            # pix^2 to arcsec^2 conversion factor
    pix2_deg2 = pix2_arcsec2/(3600**2) # pix^2 to deg^2 conversion factor
    global numFailed
    rPHI = np.empty_like(angsep)
    d_DLR = np.empty_like(angsep)

    # convert from IMAGE units (pixels) to WORLD (arcsec^2)
    A_ARCSEC = A_IMAGE*pix_arcsec
    B_ARCSEC = B_IMAGE*pix_arcsec

    # angle between RA-axis and SN-host vector
    GAMMA = np.arctan((DEC_SN - DEC)/(np.cos(DEC_SN*rad)*(RA_SN - RA)))

    # angle between semi-major axis of host and SN-host vector
    PHI = np.radians(THETA_IMAGE) + GAMMA # angle between semi-major axis of host and SN-host vector

    rPHI = A_ARCSEC*B_ARCSEC/np.sqrt((A_ARCSEC*np.sin(PHI))**2 +
                                     (B_ARCSEC*np.cos(PHI))**2)

    # directional light radius
    #  where 2nd moments are bad, set d_DLR = 99.99
    d_DLR = angsep/rPHI

    return [d_DLR, A_ARCSEC, B_ARCSEC, rPHI]

def get_zs_box(s,search_ra,search_dec,search_rad):
    survey_flags = {
    'DES_AAOmega':['1','2','3','4','6'],
    'ZFIRE_UDS':['3'],
    'NOAO_0522':['4','6'],
    'NOAO_0334':['4','6'],
    'N17B331':['4','6'],
    'MOSDEF':['Any'],
    'SpARCS':['1','2'],
    'PanSTARRS_AAOmega   ':['3','4','6'],
    'PanSTARRS_MMT': ['3','4','6'],
    'PRIMUS': ['3','4'],
    'NED': ['Any'],
    'UDS_FORS2':['A','B'],
    'UDS_VIMOS':['3','4'],
    'ACES': ['3','4'],
    'SDSS': ['0'],
    '6dF': ['4'],
    'ATLAS':['Any'],
    '2dFGRS':['3','4'],
    'GAMA':['4'],
    'SNLS_FORS           ':['1','2'],
    'CDB':['Any'],
    'VVDS_DEEP':['3','4','13','14','23','24','213','214'],
    'VVDS_CDFS':['3','4','13','14','23','24'],
    'MUSE':['3','2'],
    'SAGA':['4'],
    'SNLS_AAOmega':['3','4','6'],
    'VIPERS':['2','3','4','9','22','23','24','29','12','13','14','19','212','213','214','219'],
    'DEEP2_DR4':['-1','3','4'],
    'VUDS_COSMOS':['3','4','13','14','23','24','43','44'],
    'VUDS_ECDFS':['3','4','13','14','23','24','43','44'],
    }
    grc = Table.read(os.path.join(s.cat_dir,'ozdes_grc.fits'))
    grc['ID'] = grc['ID'].astype(str)
    grc['flag'] = grc['flag'].astype(str)
    grc['source'] = grc['source'].astype(str)
    grc['comments'] = grc['comments'].astype(str)
    grc = grc.to_pandas()
    good_redshifts = pd.DataFrame()
    for survey,flags in survey_flags.items():
        if flags !=['Any']:
            for flag in flags:
                good_redshifts = good_redshifts.append(grc[(grc['source']==survey)&(grc['flag']==flag)])
        else:
            good_redshifts = good_redshifts.append(grc[grc['source']==survey])
    good_in_search_box = (good_redshifts['RA']< search_ra+search_rad)&(good_redshifts['RA']> search_ra-search_rad) & (good_redshifts['DEC']> search_dec-search_rad) & (good_redshifts['DEC']< search_dec+search_rad)

    gals_with_z = good_redshifts[good_in_search_box]
    z_gals = SkyCoord(ra=gals_with_z['RA'].values*u.degree,dec = gals_with_z['DEC'].values*u.degree)
    return gals_with_z,z_gals

def match_gals(catcoord,galscoord,cat,gals,dist_thresh = 0.5):
    ordered_surveys = [
    'PRIMUS',
    'NED',
    'UDS_FORS2',
    'UDS_VIMOS',
    'ZFIRE_UDS',
    'ACES',
    'SDSS',
    '6dF',
    'ATLAS',
    '2dFGRS',
    'GAMA',
    'SNLS_FORS           ',
    'CDB',
    'VVDS_DEEP',
    'VVDS_CDFS',
    'MUSE',
    'SAGA',
    'DEEP2_DR4',
    'VUDS_COSMOS',
    'VUDS_ECDFS',
    'NOAO_0522',
    'NOAO_0334',
    'N17B331',
    'MOSDEF',
    'SpARCS',
    'VIPERS',
    'PanSTARRS_AAOmega   ',
    'PanSTARRS_MMT',
    'SNLS_AAOmega',
    'DES_AAOmega']



    logger = logging.getLogger(__name__)
    logger.handlers =[]
    ch = logging.StreamHandler()
    logger.setLevel(logging.INFO)
    ch.setLevel(logging.INFO)
    formatter =logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    inds,d2d,d3d = galscoord.match_to_catalog_sky(catcoord)
    init_matches = cat.iloc[inds]
    close_match_inds = d2d< dist_thresh*u.arcsec
    stack_gals_with_z = gals.iloc[close_match_inds]
    stack_gal_zs = init_matches[close_match_inds]

    logger.info('Matched %s galaxies with redshifts'%len(stack_gals_with_z))
    gals['z']= ''
    gals['z_Err']= ''
    gals['flag']= ''
    gals['source'] = ''
    stack_gals_with_z[['z','z_Err','flag','source']]=stack_gal_zs[['z','z_Err','flag','source']].set_index(stack_gals_with_z.index)

    for c,i in enumerate(stack_gals_with_z.index):
        try:
            g = stack_gals_with_z.iloc[c:c+1]
        except:
            g = stack_gals_with_z.iloc[c:]
        gobj= SkyCoord(ra=g['X_WORLD'].values*u.deg,dec = g['Y_WORLD'].values*u.deg)
        idxc,idxgals,d2d,d3d = gobj.search_around_sky(catcoord,1*u.arcsec)
        grcres = cat.iloc[idxc]
        for survey in ordered_surveys:

            for row in grcres[grcres['source']=='DES_AAOmega'].index:
                if grcres['ID'].loc[row][:10] =='SVA1_COADD':
                    ins = grcres[['z','z_Err','flag','source']].loc[row].values
                    stack_gals_with_z.loc[i,['z','z_Err','flag','source']] = ins

    gals.loc[stack_gals_with_z.index]=stack_gals_with_z
    logger.debug(gals['z'].nonzero())
    return gals

def get_edge_flags(xs,ys,dist=20):
    flags = np.zeros_like(xs)
    for counter,x in enumerate(xs):
        if x<20 or x>4080:
            flags[counter]=1
    for counter,y in enumerate(ys):
        if y<20 or y>2080:
            flags[counter]=1
    return flags
