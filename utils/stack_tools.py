'''Utils'''

import numpy as np
import pandas as pd
import seaborn as sns
from astropy.table import Table
from astropy.io import fits
from astropy.time import Time
import matplotlib.pyplot as plt
import datetime
import configparser
import os

def reduce_info(info,**kwargs):
    pass
    #Get a smaller info dataframe based on kwargs

def make_good_frame_list(stack,field,band,sig = -0.15):
    """Returns a list of images for a certain chip that are of quality sig.
    Arguments:
    field (str): (e.g. 'X2')
    band (str): (e.g. 'g')

    Keyword arguments:
    sig (float): the residual from mean ZP to clip at (float, default = -0.15)

    Returns:
    good_exps (DataFrame): A reduced DataFrame of good exposures for each (field,band)
    """
    ## 1
    ## Get median ZP for each exposure
    ## And calculate residual for each chip compared to that median
    stack.logger.info('Initiating make_good_frame_list.py')
    stack.logger.info('Finding good frames for {0}, in {1}, clipping ZP at {2}'.format(field,band,sig))

    stack.logger.info('Getting median zeropoint for each exposure, calculating residual for each image')

    info = stack.info_df
    import math
    info = info[info['FIELD']==field]
    stack.logger.debug('These are the bands available for field {0}'.format(field))
    stack.logger.debug(info.BAND.unique())
    info = info[info['BAND']==band]
    info['ZP_EXPRES']=''
    for counter,exp in enumerate(info.EXPNUM.unique()):
        this_exp = info[info['EXPNUM']==exp]
        exp_idx = this_exp.index
        med_zp = this_exp['CHIP_ZERO_POINT'].median()
        info.loc[exp_idx,'ZP_EXPRES'] = this_exp['CHIP_ZERO_POINT']-med_zp

    #stack.logger.info('Here is the column of initial residuals for each exposure')
    #stack.logger.info(info['ZP_EXPRES'])
    ######################################################
    ## 2
    ## Calculate the average residual from part 1 over all exposures for that chip (field,band)
    stack.logger.info('Getting the median zeropoint residual for all exposures for each chip')
    info['ZP_ADJ1'] = ''
    info['ZP_SIG_ADJ1'] = ''
    for counter, chip in enumerate(info.CCDNUM.unique()):

        this_chip = info[info['CCDNUM']==chip]
        chip_idx = this_chip.index
        med_zp = this_chip['ZP_EXPRES'].median()
        sig_chip_zps = this_chip['ZP_EXPRES'].std()
        ## 3
        ## Subtract that average residual from the given ZP to give an adjusted ZP
        info.loc[chip_idx,'ZP_ADJ1']=this_chip['CHIP_ZERO_POINT']-med_zp
        info.loc[chip_idx,'ZP_SIG_ADJ1']=sig_chip_zps
    #stack.logger.info('Here is the column of adjusted zeropoints')
    #stack.logger.info(info['ZP_ADJ1'])
    #####################################################
    ## 4
    ## Subtract the average ZP for each year off the individual zps for that year

    years =['Y1','Y2','Y3','Y4']
    info['ZP_RES']=''
    for year in years:
        stack.logger.info('Subtracting the median zeropoint for {0} from all exposures that year'.format(year))
        this_year = info[info['YEAR']==year]
        year_idx = this_year.index
        year_med = this_year['ZP_ADJ1'].median()
        year_sig = this_year['ZP_ADJ1'].std()
        final_resid = this_year['ZP_ADJ1']-year_med
        info.loc[year_idx,'ZP_RES']=final_resid

    #####################################################################
    ## 5
    ## Now cut exposures (field,band,chip) based on whether they make the cut and return them
    stack.logger.info('Getting rid of exposures whose ZP residual is below {0}'.format(sig))
    exps = info.EXPNUM.unique()
    zp_cut     = float(sig)
    seeing_cut = 2.5
    nbad = 15
    good_exps = []
    good_frame = pd.DataFrame()
    for exp in exps:
        this_exp = info[info['EXPNUM']==exp]
        stack.logger.info('Cutting in exposure {0}'.format(exp))
        resids = this_exp['ZP_RES']
        resids = resids.as_matrix()

        bad_resids = 0
        reformatted_resids = []
        for i in range(len(resids)):
            res = resids[i]
            res = float(res)
            reformatted_resids.append(res)
            if float(res)<zp_cut:
                bad_resids +=1
        this_exp['ZP_RES']=np.array(reformatted_resids)
        stack.logger.info('Number of frames in exposure {0} that fail the ZP cut: {1}'.format(exp,bad_resids))
        bads =bad_resids+len(this_exp[this_exp['PSF_NEA']>seeing_cut])
        if bads <nbad:
            #is a good frame
            stack.logger.info('...is a good frame!')
            good_exps.append(exp)

            good_frame = good_frame.append(this_exp)

    ## Save results
    np.savetxt(os.path.join(stack.list_dir,'good_exps_%s_%s.txt'%(field,band)),good_exps,fmt='%s')
    good_table = Table.from_pandas(good_frame.drop(['ZP_RES','ZP_EXPRES','ZP_ADJ1','ZP_SIG_ADJ1'],axis=1))
    #print (good_table)
    #stack.logger.info('Here is the good_table, to write to fits format')
    #stack.logger.info(good_table)
    good_fn = os.path.join(stack.list_dir,'good_exps_%s_%s_%s.fits'%(field,band,zp_cut))
    stack.logger.info('Writing out good exposure list to {0}'.format(good_fn))
    good_table.write(good_fn)
    return good_frame

def make_swarp_cmd(stack,MY,field,chip,band):
    """function to make swarp command to stack Nminus1_year, field chip, band"""
    stack.logger.info('Initiating make_swarp_cmd in order to make the commands to pass to swarp')
    #band = band + '    '
    ## Get the list of exposures for MY, field, chip, band.
    good = stack.good_frame
    good_band = good[good['BAND']==band]
    if MY == 'none':
        good_band_my =good_band
    else:

        good_band_my = good_band[good_band['YEAR']!='Y{0}'.format(MY)]
    good_my_exps = good_band_my['EXPNUM'].unique()
    #for each good exposure, find it's file
    stack_fns = []
    stack.logger.info('Adding files to the stack')
    for counter,exp in enumerate(good_my_exps):
        this_exp = good_band_my[good_band_my['EXPNUM']==exp]
        first = this_exp.iloc[0]
        night = first['NITE']
        #chip = first['CCDNUM']
        this_exp_fn = get_dessn_obs(stack,field,band,night,exp,chip)
        stack_fns.append(this_exp_fn)
    stack.logger.info('Added {} files'.format(counter))
    stack_fns = np.array(stack_fns)
    fn_list = os.path.join(stack.temp_dir,'stack_fns_MY%s_%s_%s_%s.lst' %(MY,field,band,chip))
    stack.logger.info('Saving list of files to stack at {0}'.format(fn_list))
    np.savetxt(fn_list,stack_fns,fmt='%s')
    if not os.path.isdir(os.path.join(stack.out_dir,'MY%s'%MY,field,band)):
        os.mkdir(os.path.join(stack.out_dir,'MY%s'%MY,field,band))

    fn_out = os.path.join(stack.out_dir,'MY%s'%MY,field,band)+'/ccd_%s.fits'%chip
    swarp_cmd = ['swarp','-IMAGEOUT_NAME','{0}'.format(fn_out),'@{0}'.format(fn_list),'-c','default.swarp']
    return swarp_cmd
#############################################
def get_des_obs_year(night):
    night = int(night)
    cp=configparser.ConfigParser()
    # read the .ini file
    cp.read('/media/data1/wiseman/des/coadding/config/snobs_params.ini')
    # Make a list of years
    years= ['Y1','Y2','Y3','Y4']
    year_night_lims = {}
    for y in years:
        year_night_lim = cp.get('year_night_lims',y)
        year_night_lims[y]=[int(lim.strip()) for lim in year_night_lim.split(',')]
    if ((night > year_night_lims['Y1'][0]) and
        (night < year_night_lims['Y1'][1])):
        year = 'Y1'
    elif ((night > year_night_lims['Y2'][0]) and
          (night < year_night_lims['Y2'][1])):
        year = 'Y2'
    elif ((night > year_night_lims['Y3'][0]) and
          (night < year_night_lims['Y3'][1])):
        year = 'Y3'
    elif ((night > year_night_lims['Y4'][0]) and
          (night < year_night_lims['Y4'][1])):
        year = 'Y4'
    else:
        raise ValueError
    return year
###############################################

def get_dessn_obs(stack, field, band, night, expnum, chipnum):
    '''Function to get the filename for a DES image for a
       given field, band, night, chip, and expnum.
       Uses an object of the Stack class.
       Returns path and name of the file requested.'''

    #------------------------------------
    # step 1 - get the year of the observation
    year = get_des_obs_year(night)
    #------------------------------------
    # step 2 - find the directory for this night
    year_dir = stack.data_dirs[year]
    glob_str = year_dir+night+'-r????'
    subdir = glob.glob(glob_str)[-1]+'/'
    # then this field
    field_glob_str = subdir+'*%s_%s*' % (field, band)
    try:
        field_subdir = glob.glob(field_glob_str)[-1]+'/'
    except IndexError:
        #that subdir doesn't have obs for our field in it
        subdir=glob.glob(glob_str)[0]+'/'
        field_glob_str = subdir+'*%s_%s*' % (field, band)
        field_subdir = glob.glob(field_glob_str)[-1]+'/'
    field_subsubdir = field_subdir + os.listdir(field_subdir)[-1]+'/'
    # then the chip
    chip_subdir = '%sccd%02d' % (field_subsubdir, chipnum)
    #------------------------------------
    # step 3 - find the final fits file at the end of the dir structure
    subdir_list = [chip_subdir]
    rabbit_hole = True
    while rabbit_hole:
        curr_subdir = '/'.join(subdir_list)
        curr_dir_cont = os.listdir(curr_subdir)
        next_subdir = '/'.join([
            curr_subdir,
            curr_dir_cont[0]])
        try:
            next_subdir_cont = os.listdir(next_subdir)
            subdir_list.append(curr_dir_cont[0])
        except:
            obs_dir = next_subdir
            rabbit_hole = False
    #------------------------------------
    # step 4 - CHECK THIS IS THE CORRECT EXPOSURE NUMBER!!!
    for base_obs_fn in os.listdir(os.path.dirname(obs_dir)):
        try:
            obs_fn = os.path.join(os.path.dirname(obs_dir),os.path.basename(base_obs_fn))
            fits_expnum = fits.getheader(obs_fn)['EXPNUM']
            #stack.logger.info('Attempted EXPNUM: {0}; Got: {1}'.format(expnum,fits_expnum))
        except:
            #stack.logger.info(base_obs_fn)
            #stack.logger.info(fits.getheader(obs_fn)['EXPNUM'])
            continue
        if fits_expnum == expnum:
            if year == 'Y4':
                obs_fn = obs_fn+'[0]'

            return obs_fn
        else:
            pass
    #return None
