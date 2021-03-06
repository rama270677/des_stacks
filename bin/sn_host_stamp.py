#!/home/wiseman/anaconda3/bin/python
# -*- coding: utf-8 -*-
'''Script to find the photometry for a certain supernova'''
# exectuable to run through the entire stack process
import numpy as np
import pandas as pd
import logging
import argparse
from time import gmtime, strftime
from astropy.coordinates import SkyCoord
from astropy import units as u
from astropy.table import Table
import astropy.io.fits as fits
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import _pickle as cpickle
import math
import glob
import seaborn as sns
import itertools


sns.set_color_codes(palette='colorblind')

plot_locs_labeled={
'g':[0.18,0.53,0.40,0.43],
'r':[0.59,0.53,0.40,0.43],
'i':[0.18,0.09,0.40,0.43],
'z':[0.59,0.09,0.40,0.43]
}

plot_locs_paper = {
'g':[0.02,0.51,0.47,0.47],
'r':[0.51,0.51,0.47,0.47],
'i':[0.02,0.02,0.47,0.47],
'z':[0.51,0.02,0.47,0.47]
}

bands = ['g','r','i','z']
pix_arcsec = 0.264
def parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('-n','--sn_name',help='Full DES supernova ID, e.g. DES16C2nm (case sensitive)',default=None)
    parser.add_argument('-ra','--ra',help='RA of target',default=None)
    parser.add_argument('-de','--dec',help='DEC of target',default=None)
    parser.add_argument('-l','--namelist',help='List of SN names as a .txt or .csv file',default = None)
    parser.add_argument('-wd','--workdir',help='Path to directory to work in',required = False,default = '/media/data3/wiseman/des/coadding')
    parser.add_argument('-d','--distance',help='Maximum allowable match radius (arcsec) for galaxy association',required=False,default=5)
    parser.add_argument('-s','--stamp',help='Produce a stamp',action ='store_true')
    parser.add_argument('-ss','--size',help='Stamp size (arcsec)',default=30,type=float)
    parser.add_argument('-sh','--show',help='Show image now', action ='store_true')
    parser.add_argument('-p','--path',help='Full path to output image if you are making a stamp',default = 'sn_dir')
    parser.add_argument('-vm','--vmin',help='vmin for greyscale',default=-0.8)
    parser.add_argument('-vx','--vmax',help='vmax for greyscale',default=15.0)
    parser.add_argument('-ne','--new',help = 'Use new stacks?',action='store_true' )
    parser.add_argument('-fc','--finder',help = 'Is this a finder chart?',action='store_true')
    parser.add_argument('-pa','--paper',help = 'Is this for a paper?',action='store_true')
    parser.add_argument('-re','--resfile',help = 'File to find host phot results for this SN',default = None)
    parser.add_argument('-b','--band',help='Only use one band? If so, enter here',default='All')
    parser.add_argument('-f','--ftype',help='File type for save. Default = pdf',default='pdf')
    parser.add_argument('-w','--width',help='Size in pixels',default=300)

    return parser.parse_args()

def get_sn_dat(sn):
    f=open('/media/data3/wiseman/des/coadding/config/chiplims.pkl','rb')
    chiplims = cpickle.load(f)
    sncand = pd.read_csv('/media/data3/wiseman/des/coadding/catalogs/sncand_db.csv')

    dat = sncand[sncand['transient_name']==sn]

    ra,dec =dat[['ra','dec']].iloc[0].values
    y = dat['season'].values[0]

    #################
    obj_field = sn[5:7]
    the_field = chiplims[obj_field]
    for ccd in the_field.keys():
        if the_field[ccd][0][0] > ra > the_field[ccd][2][0]:
            if the_field[ccd][0][1] < dec < the_field[ccd][1][1]:
                return (ra,dec,'SN-%s'%obj_field,y,ccd)

def main(args,logger):
    sn_name = args.sn_name
    match_dist = args.distance

    if sn_name:
        l = [sn_name]
    else:
        l = np.genfromtxt(args.namelist,dtype=str,delimiter='\n')
    for sn in l:
        sn_name = sn
        sn_cap_dir = os.path.join('/media/data3/wiseman/des/coadding/5yr_stacks/CAP/',sn_name)
        logger.info("Locating result file for %s ..."%sn)
        logger.info("First querying the DES database to get the RA,Dec of %s."%sn)
        sn_ra,sn_dec,f,y,chip = get_sn_dat(sn)
        logger.info("%s has the following info:"%sn)
        logger.info("RA:     %s"%sn_ra)
        logger.info("Dec:    %s"%sn_dec)
        logger.info("Season: %s"%y)
        logger.info("Field:  %s"%f)
        logger.info("CCD:    %s"%chip)
        sngals_deep = pd.read_csv('/media/data3/wiseman/des/coadding/results/sngals_deep_v6.csv',index_col=0)
        sn_res = sngals_deep[sngals_deep['TRANSIENT_NAME']==sn]
        has_spec = sn_res[sn_res['SPECZ']>0]
        if len(has_spec)>0:
            loc = has_spec.index
        host = sn_res[sn_res['DLR_RANK']==1]
        phost = sn_res[sn_res['DLR_RANK']==-1]
        if len(host)>0:
            logger.info('Found the host! \n %s'%host)

        logger.info("You want a stamp of %s too. So I'm making one."%sn)
        logger.warning("You might need AplPy installed...")
        import aplpy
        fig,ax = plt.subplots() #figsize=(16,9)
        w = args.size/3600
        ax.set_xticks([])
        ax.set_yticks([])
        for loc in ['top','right','left','bottom']:
            ax.spines[loc].set_visible(False)
        #ax.set_ylabel('Declination (J2000)',fontsize=12,labelpad = 30)
        hor_line = np.array([[sn_ra-(w/7),sn_ra+(w/7)],[sn_dec,sn_dec]])
        ver_line = np.array([[sn_ra,sn_ra],[sn_dec-(w/7),sn_dec+(w/7)]])
        if args.band !='All':
            bands = [args.band]
        else:
            bands = ['g','r','i','z']
        palette = itertools.cycle(sns.color_palette(palette='colorblind',n_colors=5))
        for counter,b in enumerate(bands):

            color = next(palette)
            if counter==1:
                color=next(palette)
            try:
                img_fn = glob.glob(os.path.join(sn_cap_dir,'ccd_*%s*_sci.resamp.fits'%b))[0]
            except:
                from des_stacks import des_stack as stack
                from des_stacks.utils.stack_tools import make_cap_stamps,get_cuts
                cuts = [get_cuts(f,b) for b in bands]
                sg,sr,si,sz = [stack.Stack(f, b, y, [str(chip)] ,'coadding',cuts[counter]) for counter,b in enumerate(bands)]
                make_cap_stamps(sg,sr,si,sz,chip,sn_name,sn_ra,sn_dec,args.width,args.width)
                img_fn = glob.glob(os.path.join(sn_cap_dir,'ccd_*%s*_sci.resamp.fits'%b))[0]

            if os.path.isfile(img_fn):

                sn_res = sn_res[sn_res['RA']<sn_ra+(w)]
                sn_res = sn_res[sn_res['RA']>sn_ra-(w)]
                sn_res = sn_res[sn_res['DEC']<sn_dec+(w)]
                sn_res = sn_res[sn_res['DEC']>sn_dec-(w)]

                img = fits.open(img_fn)
                if not args.paper:
                    plot_locs = plot_locs_labeled
                else:
                    plot_locs = plot_locs_paper

                if args.band != 'All':
                    fg = aplpy.FITSFigure(img,figure=fig)
                else:
                    fg = aplpy.FITSFigure(img,figure=fig,subplot=plot_locs[b])
                try:
                    fg.recenter(sn_ra,sn_dec,w)
                except:
                    logger.info('Could not recenter to outside the frame')

                fg.show_lines([ver_line,hor_line],color=color,linewidth=2.5)
                fg.show_grayscale(vmin=float(args.vmin),vmax=float(args.vmax))
                fg.axis_labels.hide()
                fg.tick_labels.hide()
                fg.set_theme('publication')
                fg.ticks.set_length(0)
                if args.paper:
                    fg.ticks.hide()
                fg.add_label(0.9,0.8,b,relative=True,color=color,fontsize=26,weight='bold')
                fg.add_scalebar(5/3600,color=color,linewidth=3,fontsize=20,weight='bold')
                fg.scalebar.set_label('5"')
                # now add some region ellipses and axis_labels
                try:
                    i = sn_res[(sn_res['RA']<host['RA'].values[0]+0.00001)&(sn_res['RA']>host['RA'].values[0]-0.00001)].index
                    sn_res.drop(i,inplace=True)
                except:
                    pass
                try:
                    j = sn_res[(sn_res['RA']<has_spec['RA'].values[0]+0.00001)&(sn_res['RA']>has_spec['RA'].values[0]-0.00001)].index
                    sn_res.drop(j,inplace=True)
                except:
                    pass

                if not args.finder and not args.paper:
                    try:
                        As,Bs,thetas = sn_res.A_IMAGE.values*pix_arcsec*4/3600,sn_res.B_IMAGE.values*pix_arcsec*4/3600,sn_res.THETA_IMAGE.values
                        ras,decs = sn_res.RA.values,sn_res.DEC.values
                        mags,errs = sn_res['MAG_AUTO_%s'%b.capitalize()].values,sn_res['MAGERR_AUTO_%s'%b.capitalize()].values

                        fg.show_ellipses(ras,decs,As,Bs,thetas,edgecolor='g',facecolor='none',linewidth=1,alpha=.8)
                        if len(host)>0:
                            if not math.isnan(host['SPECZ'].values[0]):
                                fg.show_ellipses(host.RA.values,host.DEC.values,4*host.A_IMAGE.values*pix_arcsec/3600,
    4*host.B_IMAGE.values*pix_arcsec/3600,host.THETA_IMAGE.values,edgecolor='r',facecolor='none',linewidth=1)
                            else:
                                fg.show_ellipses(host.RA.values,host.DEC.values,4*host.A_IMAGE.values*pix_arcsec/3600,
    4*host.B_IMAGE.values*pix_arcsec/3600,host.THETA_IMAGE.values,edgecolor='b',facecolor='none',linewidth=1)
                                fg.add_label(host.RA.values[0],host.DEC.values[0]+0.00045,'%.3f +/- %.3f'%(host['MAG_AUTO_%s'%b.capitalize()].values[0],host['MAGERR_AUTO_%s'%b.capitalize()].values[0]),
                                         size=8,color='b',weight='bold')

                        for obj in range(len(ras)):

                            if decs[obj]+0.00045 < sn_dec+w:


                                fg.add_label(ras[obj],decs[obj]+0.00045,'%.3f +/- %.3f'%(mags[obj],errs[obj]),
                                         size=7,color='g',weight='bold')
                            else:
                                fg.add_label(ras[obj],decs[obj]-0.00045,'%.3f +/- %.3f'%(mags[obj],errs[obj]),
                                         size=7,color='g',weight='bold')
                        for spec in range(len(has_spec.RA.values)):
                            row = has_spec.iloc[spec]
                            if len(host)>0:
                                if row['RA']!=host['RA'].values[0]:
                                    fg.add_label(row.RA,row.DEC+0.001,
                                             'z = %.3g'%has_spec.SPECZ.values[spec],size=7,color='b',weight='bold')
                                    fg.add_label(row.RA,row.DEC+0.00065,'%.3f +/- %.3f'%(row['MAG_AUTO_%s'%b.capitalize()],row['MAGERR_AUTO_%s'%b.capitalize()]),
                                         size=8,color='b',weight='bold')
                                    fg.show_ellipses(row.RA,row.DEC,4*row.A_IMAGE*pix_arcsec/3600,
             4*row.B_IMAGE*pix_arcsec/3600,row.THETA_IMAGE,edgecolor='b',facecolor='none',linewidth=1)
                                else:
                                    fg.add_label(row.RA,row.DEC+0.001,
                                             'z = %.3g'%has_spec.SPECZ.values[spec],size=7,color='r',weight='bold')
                                    fg.add_label(row.RA,row.DEC+0.00065,'%.3f +/- %.3f'%(row['MAG_AUTO_%s'%b.capitalize()],row['MAGERR_AUTO_%s'%b.capitalize()]),
                                         size=8,color='r',weight='bold')

                            else:
                                    fg.add_label(row.RA,row.DEC+0.001,
                                             'z = %.3g'%has_spec.SPECZ.values[spec],size=7,color='b',weight='bold')
                                    fg.add_label(row.RA,row.DEC+0.00065,'%.2f +/- %.2f'%(row['MAG_AUTO_%s'%b.capitalize()],row['MAGERR_AUTO_%s'%b.capitalize()]),
                                         size=8,color='b',weight='bold')

                    except:
                        pass
                '''if counter in [0,2]:
                    fg.tick_labels.show_y()
                if counter in [2,3]:
                    fg.tick_labels.show_x()'''
            else:
                fg = aplpy.FITSFigure('/media/data3/wiseman/des/coadding/config/blank2.fits',figure=fig,subplot=plot_locs[b])
                fg.axis_labels.hide()
                fg.tick_labels.hide()
                fg.add_label(0.5,0.5,'[Failed to load %s band image]'%b,relative=True,fontsize=12,color='black')
            if counter ==0 and not args.paper:
                fg.add_label(0.99,1.05,sn,relative=True,fontsize=14,color='black')
        if args.paper:
            plt.subplots_adjust(left=0.02,right=0.98)
        #plt.suptitle('Right Ascension (J2000)',x=0.57,y=0.04)
        if args.path =='sn_dir':
            savepath =os.path.join(sn_cap_dir,'%s_stamp.%s'%(sn,args.ftype))
        else:
            savepath =os.path.join(args.path,'%s_stamp.%s'%(sn,args.ftype))

        plt.savefig(savepath)
        plt.close(fig)
        logger.info("Figure saved to %s"%savepath)
        logger.info("************* Finished looking up %s! *************"%sn)
if __name__ == "__main__":
    logger = logging.getLogger('sn_host_lookup.py')
    logger.setLevel(logging.DEBUG)
    formatter =logging.Formatter('%(name)s - %(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    logger.info("***********************************")
    logger.info("Initialising *** sn_host_stamp.py *** at %s UT" % strftime("%Y-%m-%d %H:%M:%S", gmtime()))
    logger.info("***********************************")
    args = parser()
    main(args,logger)
    logger.info("************* Finished all SN you gave me! *************")
