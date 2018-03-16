import pathos.pools as pp
import multiprocessing
import os
import subprocess
from des_stacks.utils.stack_tools import make_swarp_cmd
import time
import numpy as np
import os
from itertools import repeat
from functools import partial
import logging
def worker(arg_pair):
    print ('TRYING')

    chip,args =arg_pair[1],arg_pair[0]
    s,y,field,band,cuts,final,logger= [args[i]for i in range(len(args))]
    started = float(time.time())
    #logger.info('Stacking chip %s; starting by creating mini-stacks to save time'%chip)
    cmd_list = make_swarp_cmd(s,y,field,chip,band,s.logger,cuts,final)
    #logger.info("Pulled commands list")
    staged_imgs = []
    print ('GOT A CMD LIST')
    for key,value in cmd_list.items():

        cmd,outname = value
        staged_imgs.append(outname)
        if cmd == False:
            #logger.info("Already stacked this chip with these cuts, going straight to astrometry")
            pass
        else:
            #s.logger.info('Stacking... please be patient.'.format(cmd))
            os.chdir(s.temp_dir)
            try:
                starttime=float(time.time())
                p = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                outs,errs = p.communicate()
                endtime=float(time.time())

            except (OSError, IOError):
                #s.logger.warn("Swarp failed.", exc_info=1)
                pass
            #s.logger.info('Finish stacking chip {0}'.format(chip))
            #s.logger.info('Took %.3f seconds' % (endtime-starttime))
        #s.logger.info('Added %s to list of images to make final stack' %outname)
    #s.logger.info('Now combining mini-stacks into final science frame')
    print ("DID A SWARP!")
    staged_list = np.array(staged_imgs)
    #s.logger.info('Combining these frames:')
    #s.logger.info(staged_list)
    staged_listname = os.path.join(s.temp_dir,'%s_%s_%s_%s_%s_staged.lst'%(y,field,band,chip,s.cutstring))
    np.savetxt(staged_listname,staged_list,fmt='%s')
    resamp_cmd =['swarp','@%s'%staged_listname,'-COMBINE','N','-RESAMPLE','Y','-c','default.swarp']
    os.chdir(s.band_dir)
    #s.logger.info('Resampling and weighting the intermediate images:\n %s'%resamp_cmd)
    res_start = float(time.time())
    rf = subprocess.Popen(resamp_cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    r_out,r_errs = rf.communicate()
    res_end = float(time.time())
    #s.logger.info('Done resampling intermediate stacks, took %.3f seconds'%(res_end-res_start))
    resamplist = []
    weightlist = []
    for img in staged_list:
        imgname = os.path.split(img)[-1]
        imgnameroot = imgname[:-5]
        resamplist.append(os.path.join(s.band_dir,imgnameroot+'.resamp.fits'))
        weightlist.append(os.path.join(s.band_dir,imgnameroot+'.resamp.weight.fits'))
    final_resampname = os.path.join(s.temp_dir,'%s_%s_%s_%s_%s_final.lst'%(y,field,band,chip,s.cutstring))
    final_weightname = os.path.join(s.temp_dir,'%s_%s_%s_%s_%s_final.wgt.lst'%(y,field,band,chip,s.cutstring))
    np.savetxt(final_resampname,resamplist,fmt='%s')
    np.savetxt(final_weightname,weightlist,fmt='%s')
    imgout_name = staged_list[0][:-7]+'_sci.fits'
    weightout_name = staged_list[0][:-7]+'_wgt.fits'
    final_cmd = ['swarp','@%s'%final_resampname,'-IMAGEOUT_NAME',imgout_name,'-c','default.swarp','-WEIGHTOUT_NAME',weightout_name,'-COMBINE_TYPE','WEIGHTED','-WEIGHT_IMAGE','@%s'%final_weightname]
    #s.logger.info('Doing this command to do the final stack:\n %s'%final_cmd)
    final_start = float(time.time())
    pf = subprocess.Popen(final_cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    f_out,f_errs = pf.communicate()
    final_end = float(time.time())
    #s.logger.info("Done combining mini-stacks, took %.3f seconds"%(final_end -final_start))
    #s.logger.info("Saved final science frame at %s"%imgout_name)
    #s.logger.info("And final weightmap at %s"%weightout_name)
    t_tot = float(time.time()) - started
    return t_tot

def multitask(s,y,field,band,cuts,final):
    n_chips = len(s.chips)

    args = [s,y,field,band,cuts,final]

    pool_size = multiprocessing.cpu_count()*2
    s.logger.info("Starting %s processes"%pool_size)
    pool = pp.ProcessPool(processes=pool_size,
                                maxtasksperchild=2,
                                )
    chips = list(s.chips)
    logger = multiprocessing.get_logger()
    logger.setLevel(logging.INFO)
    args.append(logger)
    all_args = []
    for c in chips:
        all_args.append([args,c])
    results = pool.map(worker,all_args)
    pool.close()
    pool.join()
    return results
