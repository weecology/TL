"""Module with functions to carry out analyses for the TL project"""
from __future__ import division, with_statement
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import partitions as parts
from macroecotools import AICc
import numpy as np
import scipy
from scipy import stats
import scikits.statsmodels.api as sm
import random
import csv
import signal
from pyper import *
from contextlib import contextmanager

# Define constants
Q_MIN = 5 # Minimal Q for a (Q, N) combo to be included 
N_MIN = 3 # Minimal N for a (Q, N) combo to be included
n_MIN = 5 # Minimal number of valid points in a study to be included 

class TimeoutException(Exception): pass

@contextmanager
def time_limit(seconds):
    """Function to skip step after given time"""
    def signal_handler(signum, frame):
        raise TimeoutException, 'Time out!'
    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)

def get_QN_mean_var_data(data_dir):
    """Read in data file with study, Q, and N"""
    data = np.genfromtxt(data_dir, dtype = 'S25, i15, i15, f15, f15', delimiter = '\t', 
                         names = ['study', 'Q', 'N', 'mean', 'var'])
    return data

def get_study_info(data_dir):
    """Read in data file with study, taxon, and type"""
    data = np.genfromtxt(data_dir, dtype = 'S25, S25, S25', delimiter = '\t',
                          names = ['study', 'taxon', 'type'])
    return data

def get_var_sample_file(data_dir, sample_size = 1000):
    """Read in the file generated by the function sample_var()"""
    names_data = ['study', 'Q', 'N', 'mean', 'var']
    names_sample = ['sample'+str(i) for i in xrange(1, sample_size + 1)]
    names_data.extend(names_sample)
    type_data = 'S15, i15, i15' + ',<f8'*(len(names_data) - 3)
    data = np.genfromtxt(data_dir, delimiter = '\t', names = names_data, dtype = type_data)
    return data

def get_val_ind_sample_file(data_dir, sample_size = 1000):
    """Read in a file with 'study' as the first column, value from empirical TL as the second column,
    
    and one value from each simualted sample as the rest of the columns.
    
    """
    names_data = ['study', 'emp_val']
    names_sample = ['sample'+str(i) for i in xrange(1, sample_size + 1)]
    names_data.extend(names_sample)
    type_data = 'S15' + ',<f8'*(len(names_data) - 1)
    data = np.genfromtxt(data_dir, delimiter = '\t', names = names_data, dtype = type_data, autostrip = True)
    return data

def get_tl_par_file(data_dir):
    """Read in the file generated by the function TL_form_sample()"""
    type_data = 'S15' + ',f15' * 14
    names_data = ['study', 'b_obs', 'inter_obs', 'R2_obs', 'p_obs', 'b_expc', 'inter_expc', 'R2_expc', \
                  'p_sample', 'b_z', 'b_lower', 'b_upper', 'inter_z', 'inter_lower', 'inter_upper']
    data = np.genfromtxt(data_dir, delimiter = ' ', names = names_data, dtype = type_data)
    return data
    
def RandomComposition_weak(q, n):
    indices = sorted(np.random.randint(0, q, n - 1))
    parts = [(indices + [q])[i] - ([0] + indices)[i] for i in range(len(indices)+1)]
    return parts

def rand_compositions(q, n, sample_size, zeros):
    comps = []
    while len(comps) < sample_size:
        
        comp = RandomComposition_weak(q, n)
                
        if len(comp) != n or sum(comp) != q:
            print zeros,'error: q=',q,'!=sum(comp)=',sum(comp),'or n=',n,'!=len(comp)=',len(comp)
            sys.exit()
        comp.sort()
        comp.reverse()
        comps.append(comp)
    
    comps = [list(x) for x in set(tuple(x) for x in comps)]
    return comps

def get_var_for_Q_N(q, n, sample_size, t_limit, analysis):
    """Given q and n, returns a list of variance of length sample size with variance of 
    
    each sample partitions or compositions.
    
    """
    QN_var = []
    try:
        with time_limit(t_limit):
            for Niter in range(sample_size):
                if analysis == 'partition':
                    QN_parts = parts.rand_partitions(q, n, 1, 'bottom_up', {}, True)
                else: QN_parts = rand_compositions(q, n, 1, True)
                QN_var.append(np.var(QN_parts[0], ddof = 1))
            return QN_var
    except TimeoutException, msg:
        print 'Timed out!'
        return QN_var

def sample_var(data, study, sample_size = 1000, t_limit = 7200, analysis = 'partition'):
    """Obtain and record the variance of partition or composition samples.
    
    Input:
    data - data list read in with get_QN_mean_var_data()
    study - ID of study
    sample_size - number of samples to be drawn, default value is 1000
    t_limit - abort sampling procedure for one Q-N combo after t_limit seconds, default value is 7200 (2 hours)
    analysis - partition or composition
    
    """
    data_study = data[data['study'] == study]
    var_parts = []
    for record in data_study:
        q = record[1]
        n = record[2]
        out_row = [x for x in record]
        QN_var = get_var_for_Q_N(q, n, sample_size, t_limit, analysis)
        if len(QN_var) == sample_size:
            out_row.extend(QN_var)
            var_parts.append(out_row)
        else: break # Break out of for-loop if a Q-N combo is skipped
    
    if len(data_study) == len(var_parts): # If no QN combos are omitted, print to file
        out_write_var = open('taylor_QN_var_predicted_' + analysis + '_full.txt', 'a')
        for var_row in var_parts:
            print>>out_write_var, '\t'.join([str(x) for x in var_row])
        out_write_var.close()

def get_z_score(emp_var, sim_var_list):
    """Return the z-score as a measure of the discrepancy between empirical and sample variance"""
    sd_sim = (np.var(sim_var_list, ddof = 1)) ** 0.5
    return (emp_var - np.mean(sim_var_list)) / sd_sim

def quadratic_term(list_of_mean, list_of_var):
    """Fit a quadratic term and return its p-value"""
    # Remove records with 0 variance
    log_var = [np.log(x) for x in list_of_var if x > 0]
    log_mean = [np.log(list_of_mean[i]) for i in range(len(list_of_mean)) if list_of_var[i] > 0]
    log_mean_quad = [x ** 2 for x in log_mean]
    indep_var = np.column_stack((log_mean, log_mean_quad))
    indep_var = sm.add_constant(indep_var, prepend = True)
    quad_res = sm.OLS(log_var, indep_var).fit()
    return quad_res.pvalues[2]

def fit_nls(list_of_mean, list_of_var): 
    """Apply nonlinear regression instead of linear regression on log scale
    
    and return parameter estimates for a, b, and sigma^2.
    
    """
    # Remove zero from var
    var_no_zero = np.array([x for x in list_of_var if x > 0])
    mean_no_zero = np.array([list_of_mean[i] for i in range(len(list_of_mean)) if list_of_var[i] > 0])
    b0, inter0, r, p, std_error = stats.linregress(np.log(mean_no_zero), np.log(var_no_zero))
    def func_power(x, a, b):
        return a * (x ** b)
    try:
        popt, pcov = scipy.optimize.curve_fit(func_power, mean_no_zero, var_no_zero, p0 = (np.exp(inter0), b0))
    except:
        popt = [np.exp(inter0), b0] # If failed to converge, retain parameters from linear regression
    residuals = var_no_zero - func_power(mean_no_zero, popt[0], popt[1])
    s2 = np.var(residuals, ddof = 1)
    return popt[0], popt[1], s2

def aicc_nls_ls(list_of_mean, list_of_var):
    """Return the difference in AICc values between the nonlinear and loglinear models"""
    var_no_zero = np.array([x for x in list_of_var if x > 0])
    mean_no_zero = np.array([list_of_mean[i] for i in range(len(list_of_mean)) if list_of_var[i] > 0])
    b0, inter0, r, p, std_error = stats.linregress(np.log(mean_no_zero), np.log(var_no_zero))
    s2_ls = np.var(np.log(var_no_zero) - inter0 - b0 * np.log(mean_no_zero), ddof = 1)
    a_nls, b_nls, s2_nls = fit_nls(mean_no_zero, var_no_zero)
    l_nls = np.sum(stats.norm.logpdf(var_no_zero, scale = s2_nls ** 0.5, \
                                        loc = a_nls * (mean_no_zero ** b_nls)))
    l_ls = np.sum(stats.lognorm.logpdf(var_no_zero, s2_ls ** 0.5, \
                                       scale = np.exp(inter0 + b0 * np.log(mean_no_zero))))
    try:
        delta_AICc = AICc(3, l_nls, len(var_no_zero)) - AICc(3, l_ls, len(var_no_zero))
    except: delta_AICc = 0
    return delta_AICc

def TL_from_sample(dat_sample, analysis = 'partition'):
    """Obtain the empirical and simulated TL relationship given the output file from sample_var().
    
    Here only the summary statistics are recorded for each study, instead of results from each 
    individual sample, because the analysis can be quickly re-done given the input file, without
    going through the time-limiting step of generating samples from partitions.
    The input dat_sample is in the same format as defined by get_var_sample_file().
    The output file has the following columns: 
    study, empirical b, empirical intercept, empirical R-squared, empirical p-value, mean b, intercept, R-squared from samples, 
    percentage of significant TL in samples (at alpha = 0.05), z-score between empirical and sample b, 2.5 and 97.5 percentile of sample b,
    z-score between empirical and sample intercept, 2.5 and 97.5 percentile of sample intercept.
    
    """
    study_list = sorted(np.unique(dat_sample['study']))
    for study in study_list:
        dat_study = dat_sample[dat_sample['study'] == study]
        emp_b, emp_inter, emp_r, emp_p, emp_std_err = stats.linregress(np.log(dat_study['mean']), np.log(dat_study['var']))
        b_list = []
        inter_list = []
        psig = 0
        R2_list = []
        for i_sim in dat_sample.dtype.names[5:]:
            var_sim = dat_study[i_sim][dat_study[i_sim] > 0] # Omit samples of zero variance 
            mean_list = dat_study['mean'][dat_study[i_sim] > 0]
            sim_b, sim_inter, sim_r, sim_p, sim_std_error = stats.linregress(np.log(mean_list), np.log(var_sim))
            b_list.append(sim_b)
            inter_list.append(sim_inter)
            R2_list.append(sim_r ** 2)
            if sim_p < 0.05: psig += 1
        psig /= len(dat_sample.dtype.names[5:])
        out_file = open('TL_form_' + analysis + '.txt', 'a')
        print>>out_file, study, emp_b, emp_inter, emp_r ** 2, emp_p, np.mean(b_list), np.mean(inter_list), np.mean(R2_list), \
             psig, get_z_score(emp_b, b_list), np.percentile(b_list, 2.5), np.percentile(b_list, 97.5), get_z_score(emp_inter, inter_list), \
             np.percentile(inter_list, 2.5), np.percentile(inter_list, 97.5)
        out_file.close()

def call_R_power_analysis(list_of_mean, list_of_var):
    """This function calls the R function power_analysis() 
    
    and returns estimates of exp(inter), b, and significance at alpha = 0.05.
    
    """
    r = R()
    r("source('Sup_2_Guidelines.r')")
    var_no_zero = np.array([x for x in list_of_var if x > 0])
    mean_no_zero = np.array([list_of_mean[i] for i in range(len(list_of_mean)) if list_of_var[i] > 0])
    r.assign('x', mean_no_zero)
    r.assign('y', var_no_zero)
    r('out = power_analysis(x, y, diagno = F)')
    out_lib = r.get('out')
    b_CI = out_lib['b_confint']
    if min(b_CI) < 0 < max(b_CI): sig = 0
    else: sig = 1
    return out_lib['a'], out_lib['b'], sig

def TL_from_sample_model_selection(dat_sample, analysis = 'partition'):
    """This function is similar to TL_from_sample(), except that model selection/averaging is adopted
    
    from Xiao et al. 2011.  It calls the R function power_analysis(). 
    
    """
    study_list = sorted(np.unique(dat_sample['study']))
    for study in study_list:
        dat_study = dat_sample[dat_sample['study'] == study]
        mean_study = dat_study['mean']
        var_study = dat_study['var']
        exp_inter, b, sig = call_R_power_analysis(mean_study, var_study)
        try: r2 = 1 - sum((np.log(var_study) - np.log(exp_inter * mean_study ** b)) ** 2) / \
            sum((np.log(var_study) - np.mean(np.log(var_study))) ** 2)
        except: r2 = 0
        b_list = [study, b]
        inter_list = [study, exp_inter]
        p_list = [study, sig]
        R2_list = [study, r2]
        for i_sim in dat_sample.dtype.names[5:]:
            var_sim = dat_study[i_sim][dat_study[i_sim] > 0] # Omit samples of zero variance 
            mean_list = dat_study['mean'][dat_study[i_sim] > 0]
            exp_inter, b, sig = call_R_power_analysis(mean_list, var_sim)
            try: r2 = 1 - sum((np.log(var_sim) - np.log(exp_inter * mean_list ** b)) ** 2) / \
                sum((np.log(var_sim) - np.mean(np.log(var_sim))) ** 2)
            except: r2 = 0
            b_list.append(b)
            inter_list.append(exp_inter)
            R2_list.append(r2)
            p_list.append(sig)
        out_file_b = open('TL_form_' + analysis + '_ms_b.txt', 'a')
        out_file_inter = open('TL_form_' + analysis + '_ms_inter.txt', 'a')
        out_file_r2 = open('TL_form_' + analysis + '_ms_r2.txt', 'a')
        out_file_p = open('TL_form_' + analysis + '_ms_p.txt', 'a')
        print>>out_file_b, ' \t'.join(map(str, b_list))
        print>>out_file_inter, ' \t'.join(map(str, inter_list))
        print>>out_file_r2, ' \t'.join(map(str, R2_list))
        print>>out_file_p, ' \t'.join(map(str, p_list))
        out_file_b.close()
        out_file_inter.close()
        out_file_r2.close()
        out_file_p.close()
          
#def TL_from_sample_model_selection_python(dat_sample, analysis = 'partition'):
    #"""Implement the same algorithm for model selection in python for speed"""
    #aicc_file = get_val_ind_sample_file('TL_AICc_' + analysis + '.txt') 
    #study_list = sorted(np.unique(dat_sample['study']))
    #for study in study_list:
        #dat_study = dat_sample[dat_sample['study'] == study]
        #aicc_study = aicc_file[aicc_file['study'] == study][0]
        #mean_list = dat_study['mean']
        #for i in range(4, len(dat_sample.dtype.names) + 1):
            #var_list = dat_study[dat_sample.dtype.names[i]]
            #var_sample = np.array([x for x in var_list if x > 0]) # Remove records with zero var
            #mean_sample = np.array([mean_list[j] for j in range(len(mean_list)) if var_list[j] > 0 ]) 
            ## Model selection 
            #if aicc_study[i - 3] > 2: # LR
                #b, inter, r, p, std_error = stats.linregress(np.log(mean_sample), np.log(var_sample))
                
def get_quadratic_sig_data(dat_sample, analysis = 'partition'):
    """Compute the p-value of the quadratic term for each dataset
    
    as well as all of its partitions/compositions and write results to file.
    
    """
    study_list = sorted(np.unique(dat_sample['study']))
    for study in study_list:
        p_list = [study]
        dat_study = dat_sample[dat_sample['study'] == study]
        emp_quad_p = quadratic_term(dat_study['mean'], dat_study['var'])
        p_list.append(emp_quad_p)
        for i_sim in dat_sample.dtype.names[5:]:
            var_sim = dat_study[i_sim][dat_study[i_sim] > 0] # Omit samples of zero variance 
            mean_list = dat_study['mean'][dat_study[i_sim] > 0]
            sim_quad_p = quadratic_term(mean_list, var_sim)
            p_list.append(sim_quad_p)
        out_file = open('TL_quad_p_' + analysis + '.txt', 'a')
        print>>out_file, ' \t'.join(map(str, p_list))
        out_file.close()

def aicc_nls_ls_to_file(dat_sample, analysis = 'partition'):
    """Obtain the delta-AICc for each empirical dataset and each of its simulations, then write to file"""
    study_list = sorted(np.unique(dat_sample['study']))
    for study in study_list:
        aicc_list = [study]
        dat_study = dat_sample[dat_sample['study'] == study]
        aicc_emp = aicc_nls_ls(dat_study['mean'], dat_study['var'])
        aicc_list.append(aicc_emp)
        for i_sim in dat_sample.dtype.names[5:]:
            var_sim = dat_study[i_sim][dat_study[i_sim] > 0] # Omit samples of zero variance 
            mean_list = dat_study['mean'][dat_study[i_sim] > 0]
            aicc_sim = aicc_nls_ls(mean_list, var_sim)
            aicc_list.append(aicc_sim)
        out_file = open('TL_AICc_' + analysis + '.txt', 'a')
        print>>out_file, ' \t'.join(map(str, aicc_list))
        out_file.close()
    
def TL_analysis(data, study, sample_size = 1000, t_limit = 7200, analysis = 'partition'):
    """Compare empirical TL relationship of one dataset to that obtained from random partitions or compositions."""
    data_study = data[data['study'] == study]
    data_study = data_study[data_study['N'] > 2] # Remove Q-N combos with N = 2
    var_parts = []
    for combo in data_study:
        q = combo[1]
        n = combo[2]
        QN_var = get_var_for_Q_N(q, n, sample_size, t_limit, analysis)
        if len(QN_var) == sample_size:
            var_parts.append(QN_var)
        else: break # Break out of for-loop if a Q-N combo is skipped
    
    if len(data_study) == len(var_parts): # IF no QN combos are omitted
        # 1. Predicted var for each Q-N combo
        var_study = np.zeros((len(data_study), ), dtype = [('f0', 'S25'), ('f1', int), ('f2', int), ('f3', float), 
                                                           ('f4', float), ('f5', float), ('f6', float)])
        var_study['f0'] = np.array([study] * len(data_study))
        var_study['f1'] = data_study['Q']
        var_study['f2'] = data_study['N']
        var_study['f3'] = np.array([np.mean(QN_var) for QN_var in var_parts])
        var_study['f4'] = np.array([np.median(QN_var) for QN_var in var_parts])
        var_study['f5'] = np.array([np.percentile(QN_var, 2.5) for QN_var in var_parts])
        var_study['f6'] = np.array([np.percentile(QN_var, 97.5) for QN_var in var_parts])
        out_write_var = open('taylor_QN_var_predicted_' + analysis + '.txt', 'a')
        out_var = csv.writer(out_write_var, delimiter = '\t')
        out_var.writerows(var_study)
        out_write_var.close()
        
        # 2. Predicted form of TL for study
        b_list = []
        inter_list = []
        psig = 0
        R2_list = []
        effective_sample = 0
        for i in range(sample_size):
            var_list = np.array([var_part[i] for var_part in var_parts])
            mean_list = data_study['mean']
            mean_list = mean_list[var_list != 0] # Omit samples of zero variance in computing TL
            var_list = var_list[var_list != 0]
            b, inter, rval, pval, std_err = stats.linregress(np.log(mean_list), np.log(var_list))
            b_list.append(b)
            inter_list.append(inter)
            R2_list.append(rval ** 2)
            if pval < 0.05: psig += 1
        psig = psig / sample_size
        OUT = open('taylor_form_predicted_' + analysis + '.txt', 'a')
        print>>OUT, study, psig, np.mean(R2_list), np.mean(b_list), np.median(b), np.percentile(b_list, 2.5), \
             np.percentile(b_list, 97.5), np.mean(inter_list), np.median(inter_list), np.percentile(inter_list, 2.5), \
             np.percentile(inter_list, 97.5)
        OUT.close()

def inclusion_criteria(dat_study, sig = False):
    """Criteria that datasets need to meet to be included in the analysis"""
    b, inter, rval, pval, std_err = stats.linregress(np.log(dat_study['mean']), np.log(dat_study['var']))
    dat_study = dat_study[(dat_study['N'] >= N_MIN) * (dat_study['Q'] >= Q_MIN)]
    if len(dat_study) >= n_MIN: 
        if ((not sig) or (pval < 0.05)): # If significance is not required, or if the relationship is significant
            return True
    else: return False

# Below are functions for plotting
def plot_obs_expc(obs, expc, expc_upper, expc_lower, obs_type, loglog, legend = False, loc = 2, ax = None):
    """Generic function to generate an observed vs expected figure with 1:1 line, 
    
    with obs on the x-axis, expected on the y-axis, and shading for CI of expected.
    Input: 
    obs - list of observed values
    expc - list of expected values, the same length as obs
    expc_upper - list of the upper percentile of expected values, the same length as obs
    expc_lower - list of the lower percentile of expected values, the same length as obs
    obs_type - list of the same length of obs, specifying whether each obs is spatial (red) or temporal (blue)
    loglog - whether both axes are to be transformed
    legend - if legend is to be included
    loc - if legend is True, the location of the legend (default at upper left)
    ax - whether the plot is generated on a given figure, or a new plot object is to be created
    
    """
    obs, expc, expc_upper, expc_lower = list(obs), list(expc), list(expc_upper), list(expc_lower)
    if not ax:
        fig = plt.figure(figsize = (3.5, 3.5))
        ax = plt.subplot(111)
    
    if loglog:
        axis_min = 0.9 * min([x for x in obs if x > 0] + [y for y in expc if y > 0])
        axis_max = 3 * max(obs + expc)
        ax.set_xscale('log')
        ax.set_yscale('log')        
    else:
        axis_min = 0.9 * min(obs + expc)
        axis_max = 1.1 * max(obs + expc)

    # Sort all lists with respect to obs
    index = sorted(range(len(obs)), key = lambda k: obs[k])
    expc = [expc[i] for i in index]
    expc_upper = [expc_upper[i] for i in index]
    expc_lower = [expc_lower[i] for i in index]
    obs = [obs[i] for i in index]
    obs_type = [obs_type[i] for i in index]
     
    # Replace zeros in expc_lower with the minimal value above zero for the purpose of plotting
    expc_lower_min = min([x for x in expc_lower if x > 0])
    expc_lower = [expc_lower_min if x == 0 else x for x in expc_lower]
    
    i_spac = [i for i, x in enumerate(obs_type) if x == 'spatial']
    i_temp = [i for i, x in enumerate(obs_type) if x == 'temporal']
    
    plt.fill_between(obs, expc_lower, expc_upper, color = '#FF83FA', alpha = 0.5)
    spat = plt.scatter([obs[i] for i in i_spac], [expc[i] for i in i_spac], c = '#EE4000',  \
                        edgecolors='none', alpha = 0.5, s = 8, label = 'Spatial')
    temp = plt.scatter([obs[i] for i in i_temp], [expc[i] for i in i_temp], c = '#1C86EE',  \
                        edgecolors='none', alpha = 0.5, s = 8, label = 'Temporal')   
    plt.plot([axis_min, axis_max],[axis_min, axis_max], 'k-')
    plt.xlim(axis_min, axis_max)
    plt.ylim(axis_min, axis_max)
    if legend:
        plt.legend([spat, temp], ['Spatial', 'Temporal'], scatterpoints = 1, loc = loc, prop = {'size': 8})
    ax.tick_params(axis = 'both', which = 'major', labelsize = 6)
    return ax

def plot_obs_expc_alt(obs, expc, obs_type, loglog, ax = None):
    """Alternative visual representation of the obs-expc plot, with not CI range but each dot plotted
    
    semi-transparently to illustrate the heat of different values. 
    Input: 
    obs - list of observed values
    expc - list of lists of expected values, each sublist is of the same length as obs, the number of sublists equal sample size 
    obs_type - list of the same length of obs, specifying whether each obs is spatial (red) or temporal (blue)
    loglog - whether both axes are to be transformed
    ax - whether the plot is generated on a given figure, or a new plot object is to be created
    
    """
    obs = list(obs)
    n_sample = len(expc)
    if not ax:
        fig = plt.figure(figsize = (3.5, 3.5))
        ax = plt.subplot(111)
    
    if loglog:
        expc_above_zero = [[x for x in sublist if x > 0] for sublist in expc]
        axis_min = 0.9 * np.min(expc_above_zero)
        axis_max = 3 * np.max(expc)
        ax.set_xscale('log')
        ax.set_yscale('log')        
    else:
        axis_min = 0.9 * np.min(expc)
        axis_max = 1.1 * np.max(expc)

    # Sort all lists with respect to obs
    index = sorted(range(len(obs)), key = lambda k: obs[k])
    expc = [expc[i] for i in index]
    expc_upper = [expc_upper[i] for i in index]
    expc_lower = [expc_lower[i] for i in index]
    obs = [obs[i] for i in index]
    obs_type = [obs_type[i] for i in index]
     
    # Replace zeros in expc_lower with the minimal value above zero for the purpose of plotting   
    i_spac = [i for i, x in enumerate(obs_type) if x == 'spatial']
    i_temp = [i for i, x in enumerate(obs_type) if x == 'temporal']
     
    for j in range(n_sample):  
        expc_sample = expc[j]
        plt.scatter([obs[i] for i in i_spac], [expc_sample[i] for i in i_spac], c = '#EE4000',  edgecolors='none', alpha = 1 / n_sample * 10, s = 8)
        plt.scatter([obs[i] for i in i_temp], [expc_sample[i] for i in i_temp], c = '#1C86EE',  edgecolors='none', alpha = 1 / n_sample * 10, s = 8)   
    plt.plot([axis_min, axis_max],[axis_min, axis_max], 'k-')
    plt.xlim(axis_min, axis_max)
    plt.ylim(axis_min, axis_max)
    ax.tick_params(axis = 'both', which = 'major', labelsize = 6)
    return ax

def plot_mean_var(mean, obs_var, expc_var, obs_type, loglog = True, ax = None):
    """Plot the observed and expected variance against mean, distinguishing 
    
    between spatial and temporal data.
    
    """
    mean, obs_var, expc_var = list(mean), list(obs_var), list(expc_var)
    if not ax:
        fig = plt.figure(figsize = (3.5, 3.5))
        ax = plt.subplot(111)
    
    if loglog:
        ax.set_xscale('log')
        ax.set_yscale('log')        
    
    i_spac = [i for i, x in enumerate(obs_type) if x == 'spatial']
    i_temp = [i for i, x in enumerate(obs_type) if x == 'temporal']
    
    plt.scatter([mean[i] for i in i_spac], [obs_var[i] for i in i_spac], c = '#EE4000',  edgecolors='none', alpha = 0.5, s = 8)
    plt.scatter([mean[i] for i in i_temp], [obs_var[i] for i in i_temp], c = '#1C86EE',  edgecolors='none', alpha = 0.5, s = 8)
    plt.scatter(mean, expc_var, c = 'black', edgecolors = 'none', alpha = 0.5, s = 8)
    ax.tick_params(axis = 'both', which = 'major', labelsize = 6)
    plt.xlabel('Mean', fontsize = 8)
    plt.ylabel('Variance', fontsize = 8)
    return ax

def comp_dens(val_list, cov_factor):
    """Compute the density function given covariance factor."""
    density = stats.gaussian_kde(val_list)
    density.covariance_factor = lambda :  cov_factor
    density._compute_covariance()
    return density

def plot_dens(obs, expc, obs_type, ax = None, legend = False, loc = 2):
    """Plot the density of observed and expected values, with spatial and temporal observations 
    
    distinguished by color.
    
    """
    if not ax:
        fig = plt.figure(figsize = (3.5, 3.5))
        ax = plt.subplot(111)
    
    obs_spatial = [obs[i] for i in range(len(obs)) if obs_type[i] == 'spatial']
    obs_temporal = [obs[i] for i in range(len(obs)) if obs_type[i] == 'temporal']
    full_values = list(obs) + list(expc)
    min_plot, max_plot = 0.9 * min(full_values), 1.1 * max(full_values)
    xs = np.linspace(min_plot, max_plot, 200)
    cov_factor = 0.2
    dens_obs_spatial = comp_dens(obs_spatial, cov_factor)
    dens_obs_temporal = comp_dens(obs_temporal, cov_factor)
    dens_expc = comp_dens(expc, cov_factor)
    spat, = plt.plot(xs, dens_obs_spatial(xs), c = '#EE4000')
    temp, = plt.plot(xs, dens_obs_temporal(xs), c = '#1C86EE')
    feas, = plt.plot(xs, dens_expc(xs), 'k-')
    if legend:
        plt.legend([spat, temp, feas], ['Spatial', 'Temporal', 'Feasible Set'], loc = loc, prop = {'size': 8})
    ax.tick_params(axis = 'both', which = 'major', labelsize = 6)
    return ax