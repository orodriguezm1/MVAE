"""
@author: Oscar Rodriguez
"""

import numpy as np
# Tensorflow
import tensorflow as tf
import tensorflow_probability as tfp
tfd = tfp.distributions
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.layers import Dense, Reshape
tfpl = tfp.layers
DenseFlipout = tfpl.DenseFlipout
from tensorflow.keras.models import Sequential
import matplotlib.pyplot as plt
from time import time
import math

start_time = time() # Initial time

# ---------------------------------------------------------------------------
###### Custom functions
# ---------------------------------------------------------------------------

tf.random.set_seed(123)

@tf.function
def ten_log(x):
    return tf.math.log(x)/tf.math.log(10.)

def fun_part_uni(xx):
    x = (xx)**2
    return x/tf.reshape(tf.math.reduce_sum(x,1),shape=(xx.shape[0],1))

# ---------------------------------------------------------------------------
###### Data generation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Initial values

np.random.seed(42) # Seed for random values
mu = 4*np.pi*1E-7  # Magnetic Permeability (H/m)
samples = 40000 # Samples for training set
samples_val = 10000 # Samples for validation set
thick_layer = 5 # Layers of subsurface
pr_training = tfd.Uniform(0.1,4.) # Probability distribution to obtain synthetic data
# log-resistivities
resistivities_training = tf.constant(pr_training.sample((1,samples,thick_layer)),tf.float32)
# Deep of subsurface layers (2000 m)
thicknesses_training = 2000*tf.math.softmax(tf.constant(tf.random.uniform((1,samples,thick_layer),0.,1),tf.float32))
n = resistivities_training.shape[2]; # Dimension of the resistivities
m = 50; # Number of frequencies
np_fr = 10**np.linspace(-2,3,m) # Frequencies in [10**-2,10**3]
frequencies = np_fr.tolist() # List of frequencies
porcentual_error = .03 # Standard deviation of error


# ---------------------------------------------------------------------------
# One-dimensional MT Forward Problem

@tf.function
def FP(x1,x2):
    list_apres = []
    list_phase = []    
    thicknesses = x1#.numpy()
    # thicknesses = 100*x[:,:,n:]#u_t*tf.math.softmax((x[:,:,n:]))#.numpy()
    resistivities = 10**x2
    for frequency in frequencies:   
        w =  2*np.pi*frequency;       
        impedancesR = list(range(n));
        impedancesC = list(range(n));
        #compute basement impedance
        impedancesR[n-1] = tf.math.sqrt(w*mu*resistivities[:,:,n-1]/2);
        impedancesC[n-1] = tf.math.sqrt(w*mu*resistivities[:,:,n-1]/2);
        for j in range(n-2,-1,-1):
            resistivity = tf.cast(resistivities[:,:,j],tf.float32);
            thickness = tf.cast(thicknesses[:,j],tf.float32);
            # 3. Compute apparent resistivity from top layer impedance
            #Step 2. Iterate from bottom layer to top(not the basement) 
            # Step 2.1 Calculate the intrinsic impedance of current layer
            djR = tf.math.sqrt((w * mu * (1.0/resistivity))/2);
            djC = tf.math.sqrt((w * mu * (1.0/resistivity))/2);
            wjR = djR * resistivity;
            wjC = djC * resistivity;
            # Step 2.2 Calculate Exponential factor from intrinsic impedance
            ejR = tf.math.exp(-2*thickness*djR)*tf.math.cos(-2*thickness*djC);   
            ejC = -tf.math.exp(-2*thickness*djR)*tf.math.sin(2*thickness*djC); 
            # Step 2.3 Calculate reflection coeficient using current layer
            #          intrinsic impedance and the below layer impedance
            belowImpedanceR = impedancesR[j + 1];
            belowImpedanceC = impedancesC[j + 1];
            rjR = (tf.math.square(wjR)+tf.math.square(wjC)-tf.math.square(belowImpedanceR)-tf.math.square(belowImpedanceC))/(tf.math.square(wjR+belowImpedanceR)+tf.math.square(wjC+belowImpedanceC));
            rjC = (2*wjC*belowImpedanceR-2*wjR*belowImpedanceC)/(tf.math.square(wjR+belowImpedanceR)+tf.math.square(wjC+belowImpedanceC));
            reR = rjR*ejR - rjC*ejC;
            reC = rjR*ejC + rjC*ejR;
            auxR = (1-tf.math.square(reR)-tf.math.square(reC))/(tf.math.square(1+reR)+tf.math.square(reC))# ((1 - re)/(1 + re)) R
            auxC = -(2*reC)/(tf.math.square(1+reR)+tf.math.square(reC)) # ((1 - re)/(1 + re)) I
            ZjR = wjR*auxR - wjC*auxC;
            ZjC = wjR*auxC + wjC*auxR;
            impedancesR[j] = ZjR;
            impedancesC[j] = ZjC;
        # Step 3. Compute apparent resistivity from top layer impedance
        ZR = impedancesR[0];
        ZC = impedancesC[0];
        absZ = tf.math.sqrt(tf.math.square(ZR)+tf.math.square(ZC));
        apparentResistivity = (absZ * absZ)/(mu * w);
        phase = tf.math.atan2(ZC, ZR);
        list_apres.append(apparentResistivity)
        list_phase.append(phase)
    aRes = ten_log(tf.convert_to_tensor(list_apres, dtype=tf.float32))
    phas = tf.convert_to_tensor(list_phase, dtype=tf.float32)
    formation = tf.reshape(tf.transpose(tf.concat([aRes,phas],0)),(x2.shape[0],x2.shape[1],2*m))
    return formation

# ---------------------------------------------------------------------------
# Data Training

X_training = tf.concat([resistivities_training,thicknesses_training],2) # Subsurface properties
FP_data = FP(X_training[0,:,n:],X_training[:,:,:n])
noise_tr = tfd.Normal(loc = FP_data, scale = tf.math.abs(FP_data)*porcentual_error)
Y_training_1 = tf.reshape(noise_tr.sample(1), FP_data.shape)
Y_training = tf.concat([thicknesses_training,Y_training_1],2) # Training set with Gaussian noise

# ---------------------------------------------------------------------------
# Data Validation
if samples>=1:
    resistivities_val = tf.constant(pr_training.sample((1,samples_val,thick_layer)),tf.float32)
    thicknesses_val = 2000*tf.math.softmax(tf.constant(tf.random.uniform((1,samples_val,thick_layer),0,1),tf.float32))
    list_val = []
    X_val = tf.concat([resistivities_val,thicknesses_val],2) # Subsurface properties
    Y_val_1 = FP(X_val[0,:,n:],X_val[:,:,:n])
    Y_val = tf.concat([thicknesses_val,Y_val_1],2) # Validation set

# ---------------------------------------------------------------------------
##### End Data generation
# ---------------------------------------------------------------------------
    
# ---------------------------------------------------------------------------
###### Return Functions
# ---------------------------------------------------------------------------

scale_x = 3 # Scale samples of x between (-scale_x,scale_x)
up_bound = 2 

def fun_return(x): # Return the mixture parameters
    s = model(x)
    pro = fun_part_uni(tf.reshape(s[:,:,2*dim_out],shape=(x.shape[0],Mixture,)))
    sig = tf.reshape(tf.math.softplus(s[:,:,dim_out:2*dim_out]),shape=(x.shape[0],Mixture,dim_out))
    loc_preds = 4*tf.math.sigmoid(tf.cast(tf.reshape(s[:,:,:dim_out],shape=(x.shape[0],Mixture,dim_out)),dtype=tf.float32))
    return pro, sig, loc_preds

def dis_ret(x,sample_): # Return the mixture samples
    s = model(x)
    pro = fun_part_uni(tf.reshape(s[:,:,2*dim_out],shape=(x.shape[0],Mixture,)))
    sig = tf.reshape(tf.math.softplus(s[:,:,dim_out:2*dim_out]),shape=(x.shape[0],Mixture,dim_out))
    loc_preds = 4*tf.math.sigmoid(tf.cast(tf.reshape(s[:,:,:dim_out],shape=(x.shape[0],Mixture,dim_out)),dtype=tf.float32))
    u1 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,0,:],sig[:,0,:],.1,4.), reinterpreted_batch_ndims=1)
    u2 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,1,:],sig[:,1,:],.1,4.), reinterpreted_batch_ndims=1)
    u3 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,2,:],sig[:,2,:],.1,4.), reinterpreted_batch_ndims=1)
    u4 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,3,:],sig[:,3,:],.1,4.), reinterpreted_batch_ndims=1)
    u5 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,4,:],sig[:,4,:],.1,4.), reinterpreted_batch_ndims=1)
    q = tfd.Mixture(cat=tfd.Categorical(probs=pro),components=[u1,u2,u3,u4,u5])
    samples_q = tf.cast(q.sample(sample_),tf.float32)
    return samples_q

# ---------------------------------------------------------------------------
###### End Return Functions
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
###### Bayesian Neural Network API
# ---------------------------------------------------------------------------

tf.random.set_seed(42)

inp = 2*m # Input dimension
dim_out = n # Output dimension
Mixture = 5 # Number of densities
out = Mixture*(2*dim_out + 1) # Output of NN

# ---------------------------------------------------------------------------
# equential model construction
nodes_NN = [300,300] # Nodes and layers
nodes_NN.append(out)
functions_NN = ['tanh','softplus']
fun_out = 'linear'
functions_NN.append(fun_out)
model_x = Sequential()
for i in range(len(nodes_NN)):
    if i==0:
        model_x.add(Dense(nodes_NN[i], input_shape=(inp,), activation=functions_NN[i],use_bias=False,name="Input_layer"))
    elif i==(len(nodes_NN)-1):
        model_x.add(Dense(nodes_NN[i], activation=functions_NN[i],use_bias=True,name="Ouput_layer"))
    else:
        model_x.add(Dense(nodes_NN[i], activation=functions_NN[i],use_bias=False,name='Hidden_layer_'+str(i)))    
model_x.add(Reshape((Mixture,2*dim_out + 1),input_shape=(out,)))


# ---------------------------------------------------------------------------
###### Autoencoder
# ---------------------------------------------------------------------------

tf.random.set_seed(42)

class MyBNN(tf.keras.Model):
    def __init__(self, Mixture, sampl_=1, name=None):
        super(MyBNN, self).__init__()
        self.loc_net = model_x
        self.sampl = sampl_
        self.var_lik = tf.Variable(0.,name='std',trainable=False)
        self.cold = tf.Variable(0.,name='cold',trainable=False)
    
    def call(self, x):
        return self.loc_net(x[:,n:])

# ELBO loss funtion (abs)
    def MyELBO(self,x,s):
        pro = fun_part_uni(tf.reshape(s[:,:,2*dim_out],shape=(x.shape[0],Mixture,)))
        sig = tf.reshape(tf.math.softplus(s[:,:,dim_out:2*dim_out]),shape=(x.shape[0],Mixture,dim_out,))
        loc_preds = 4*tf.math.sigmoid(tf.reshape(s[:,:,:dim_out],shape=(x.shape[0],Mixture,dim_out,)))
        u1 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,0,:],sig[:,0,:],.1,3.9), reinterpreted_batch_ndims=1)
        u2 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,1,:],sig[:,1,:],.1,3.9), reinterpreted_batch_ndims=1)
        u3 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,2,:],sig[:,2,:],.1,3.9), reinterpreted_batch_ndims=1)
        u4 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,3,:],sig[:,3,:],.1,3.9), reinterpreted_batch_ndims=1)
        u5 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,4,:],sig[:,4,:],.1,3.9), reinterpreted_batch_ndims=1)
        q = tfd.Mixture(cat=tfd.Categorical(probs=pro),components=[u1,u2,u3,u4,u5,])
        u1_ = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,0,:],sig[:,0,:],.0,4.), reinterpreted_batch_ndims=1)
        u2_ = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,1,:],sig[:,1,:],.0,4.), reinterpreted_batch_ndims=1)
        u3_ = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,2,:],sig[:,2,:],.0,4.), reinterpreted_batch_ndims=1)
        u4_ = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,3,:],sig[:,3,:],.0,4.), reinterpreted_batch_ndims=1)
        u5_ = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,4,:],sig[:,4,:],.0,4.), reinterpreted_batch_ndims=1)
        q_ = tfd.Mixture(cat=tfd.Categorical(probs=pro),components=[u1_,u2_,u3_,u4_,u5_,])
        self.samples_q = q.sample(self.sampl) # Samples of Mixture
        #-- Prior distribution of x
        p = tfd.Uniform(0., 4.)
       
        self.FP_pred = FP(x[:,:n],self.samples_q) # y prediction
        likelihood = tfd.Normal(0., tf.math.abs(0.03*self.FP_pred))
        log_like =  - (tf.reduce_mean(likelihood.log_prob(self.FP_pred-x[:,n:]))) + tf.reduce_mean(q_.log_prob(self.samples_q)) - (tf.reduce_mean(p.log_prob(self.samples_q))) 
        return (log_like)

# log-likelihood loss funtion
    def MyMet(self,x,s):
        likelihood = tfd.Normal(0.,tf.math.abs(x[:,n:])*porcentual_error)
        log_like = - tf.reduce_mean(likelihood.log_prob(self.FP_pred-x[:,n:]))
        return log_like
    


def map_ret(x,sample_):
    s = model(x)
    pro = fun_part_uni(tf.reshape(s[:,:,2*dim_out],shape=(x.shape[0],Mixture,)))
    sig = tf.reshape(tf.math.softplus(s[:,:,dim_out:2*dim_out]),shape=(x.shape[0],Mixture,dim_out))
    loc_preds = 4*tf.math.sigmoid(tf.cast(tf.reshape(s[:,:,:dim_out],shape=(x.shape[0],Mixture,dim_out)),dtype=tf.float32))
    u1 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,0,:],sig[:,0,:],.1,4.), reinterpreted_batch_ndims=1)
    u2 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,1,:],sig[:,1,:],.1,4.), reinterpreted_batch_ndims=1)
    u3 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,2,:],sig[:,2,:],.1,4.), reinterpreted_batch_ndims=1)
    u4 = tfd.Independent(tfd.TruncatedNormal(loc_preds[ :,3,:],sig[:,3,:],.1,4.), reinterpreted_batch_ndims=1)
    u5 = tfd.Independent(tfd.TruncatedNormal(loc_preds[:,4,:],sig[:,4,:],.1,4.), reinterpreted_batch_ndims=1)
    q = tfd.Mixture(cat=tfd.Categorical(probs=pro),components=[u1,u2,u3,u4,u5])
    samples_q = tf.cast(q.sample(sample_),tf.float32)
    ss = -q.log_prob(samples_q).numpy()
    ind = np.where(ss == np.amin(ss))
    return samples_q[ind[0][0],:,:]


def sig_return(xx,mu,sigma,sam): # Return the mixture parameters
    q = tfd.Independent(tfd.TruncatedNormal(mu[:,:],sigma[:,:],.1,4.), reinterpreted_batch_ndims=1)
    sig_FP = tf.math.reduce_std(FP(xx,q.sample(sam)),0)
    return sig_FP

# ---------------------------------------------------------------------------

his_loss_tr = []
his_loss_val = []
his_met_tr = []
his_met_val = []

epp = [1000] # Epochs
l_r = [10**-5] # Learning rate
b_s = 500 # Batch size
c_ = math.inf

for i in range(len(epp)):
    model = MyBNN(Mixture)
    opt = Adam(learning_rate=l_r[i],epsilon=1e-16)
    model.compile(optimizer=opt,loss=model.MyELBO,metrics=[model.MyMet,model.MyELBO])
    ep = epp[i]
    ii = samples
    for j in range(int(samples/ii)):
        histo = model.fit(Y_training[0,:int((j+1)*ii),:],Y_training[0,:int((j+1)*ii),:],batch_size=b_s,epochs=ep,
                            validation_data=(Y_val[0,:,:],Y_val[0,:,:]),verbose=1)
        his_loss_tr.extend(histo.history['loss'])
        his_loss_val.extend(histo.history['val_loss'])
        his_met_tr.extend(histo.history['MyMet'])
        his_met_val.extend(histo.history['val_MyMet'])
            
    if math.isnan(his_loss_tr[-1])!=True and c_>=his_loss_tr[-1]:
        c_ = his_loss_tr[-1]
        # model.save_weights('my_wei_v5l')

# model.save_weights('my_wei_v5l')
# 
 
plt.plot((np.asarray(his_loss_tr).reshape(-1)))
plt.plot((np.asarray(his_loss_val).reshape(-1)))
plt.show()

plt.plot((np.asarray(his_met_tr).reshape(-1)))
plt.plot((np.asarray(his_met_val).reshape(-1)))
plt.show()

time_train = time() - start_time # 271 min
print('Time of Training:',time_train/60)

# ---------------------------------------------------------------------------

sample_grap = 10**5 # Samples to generate the mixture estimation for the inverse problem
val = 3500 # Sample of validation set

Y_val_ = Y_val[0,val:val+1,:]
pl = dis_ret(Y_val_,sample_grap).numpy()
map_rr = map_ret(Y_val_,sample_grap)
map_r = np.reshape(map_rr,(map_rr.shape[0],1,n))
map_r_sig = tf.math.reduce_std(pl,0)
plo = tf.reduce_mean(pl,0)
p, sig, lo = fun_return(Y_val_)
mup = lo

aRes_tr = Y_val_[0:1,n:m+n]
phas_tr = (180/np.pi)*Y_val_[0:1,m+n:]  
aRes_M1 = FP(Y_val_[:,:n],mup[:,0:1,:])[:,:,:m]
phas_M1 = (180/np.pi)*FP(Y_val_[:,:n],mup[:,0:1,:])[:,:,m:]
sig_M1 = sig_return(Y_val_[:,:n],lo[:,0,:],sig[:,0,:],sample_grap)
sig_aRes_M1 = sig_M1[:,:m]
sig_phas_M1 = (180/np.pi)*sig_M1[:,m:]
aRes_M2 = FP(Y_val_[:,:n],mup[:,1:2,:])[:,:,:m]
phas_M2 = (180/np.pi)*FP(Y_val_[:,:n],mup[:,1:2,:])[:,:,m:]
sig_M2 = sig_return(Y_val_[:,:n],lo[:,1,:],sig[:,1,:],sample_grap)
sig_aRes_M2 = sig_M2[:,:m]
sig_phas_M2 = (180/np.pi)*sig_M2[:,m:]
aRes_M3 = FP(Y_val_[:,:n],mup[:,2:3,:])[:,:,:m]
phas_M3 = (180/np.pi)*FP(Y_val_[:,:n],mup[:,2:3,:])[:,:,m:]
sig_M3 = sig_return(Y_val_[:,:n],lo[:,2,:],sig[:,2,:],sample_grap)
sig_aRes_M3 = sig_M3[:,:m]
sig_phas_M3 = (180/np.pi)*sig_M3[:,m:]
aRes_M4 = FP(Y_val_[:,:n],mup[:,3:4,:])[:,:,:m]
phas_M4 = (180/np.pi)*FP(Y_val_[:,:n],mup[:,3:4,:])[:,:,m:]
sig_M4 = sig_return(Y_val_[:,:n],lo[:,3,:],sig[:,3,:],sample_grap)
sig_aRes_M4 = sig_M4[:,:m]
sig_phas_M4 = (180/np.pi)*sig_M4[:,m:]
aRes_M5 = FP(Y_val_[:,:n],mup[:,4:5,:])[:,:,:m]
phas_M5 = (180/np.pi)*FP(Y_val_[:,:n],mup[:,4:5,:])[:,:,m:]
sig_M5 = sig_return(Y_val_[:,:n],lo[:,4,:],sig[:,4,:],sample_grap)
sig_aRes_M5 = sig_M5[:,:m]
sig_phas_M5 = (180/np.pi)*sig_M5[:,m:]

aRes_MAP = FP(Y_val_[:,:n],map_r)[:,:,:m]
phas_MAP = (180/np.pi)*FP(Y_val_[:,:n],map_r)[:,:,m:]
sig_MAP = sig_return(Y_val_[:,:n],map_rr,map_r_sig,sample_grap)
sig_aRes_MAP = sig_MAP[:,:m]
sig_phas_MAP = (180/np.pi)*sig_MAP[:,m:]


resis_es = pl.reshape((sample_grap,n))
thick_es = tf.repeat(Y_val_[:,:n],sample_grap,axis=0)
aRes_es = FP(Y_val_[:,:n],pl)[:,:,:m]
phas_es = (180/np.pi)*FP(Y_val_[:,:n],pl)[:,:,m:]


# ---------------------------------------------------------------------------
# Return Values


np.savetxt('aRes_training_1d',np.asarray(aRes_tr).reshape(-1),fmt='%.7f')
np.savetxt('phas_training_1d',np.asarray(phas_tr).reshape(-1),fmt='%.7f')
np.savetxt('aRes_Estimation_1d',np.asarray(aRes_es).reshape(-1),fmt='%.7f')
np.savetxt('phas_Estimation_1d',np.asarray(phas_es).reshape(-1),fmt='%.7f')
np.savetxt('resistivity_training_1d',np.asarray(X_val[0:1,val:val+1,:n]).reshape(-1),fmt='%.7f')
np.savetxt('thicknesses_training_1d',np.asarray(X_val[0:1,val:val+1,n:]).reshape(-1),fmt='%.7f')
np.savetxt('resistivity_Estimation_1d',np.asarray(resis_es).reshape(-1),fmt='%.7f')
np.savetxt('thicknesses_Estimation_1d',np.asarray(thick_es).reshape(-1),fmt='%.7f')
np.savetxt('loss_tr',np.asarray(his_loss_tr).reshape(-1),fmt='%.7f')
np.savetxt('loss_va',np.asarray(his_loss_val).reshape(-1),fmt='%.7f')
np.savetxt('metrics_tr',np.asarray(his_met_tr).reshape(-1),fmt='%.7f')
np.savetxt('metrics_val',np.asarray(his_met_val).reshape(-1),fmt='%.7f')
np.savetxt('resistivity_training_MAP',np.asarray(map_r).reshape(-1),fmt='%.7f')
np.savetxt('thicknesses_training_MAP',np.asarray(Y_val_[:,:n]).reshape(-1),fmt='%.7f')
np.savetxt('resistivity_training_M1',np.asarray(mup[:,0:1,:]).reshape(-1),fmt='%.7f')
np.savetxt('thicknesses_training_M1',np.asarray(Y_val_[:,:n]).reshape(-1),fmt='%.7f')
np.savetxt('resistivity_training_M2',np.asarray(mup[:,1:2,:]).reshape(-1),fmt='%.7f')
np.savetxt('thicknesses_training_M2',np.asarray(Y_val_[:,:n]).reshape(-1),fmt='%.7f')
np.savetxt('resistivity_training_M3',np.asarray(mup[:,2:3,:]).reshape(-1),fmt='%.7f')
np.savetxt('thicknesses_training_M3',np.asarray(Y_val_[:,:n]).reshape(-1),fmt='%.7f')
np.savetxt('resistivity_training_M4',np.asarray(mup[:,3:4,:]).reshape(-1),fmt='%.7f')
np.savetxt('thicknesses_training_M4',np.asarray(Y_val_[:,:n]).reshape(-1),fmt='%.7f')
np.savetxt('resistivity_training_M5',np.asarray(mup[:,4:5,:]).reshape(-1),fmt='%.7f')
np.savetxt('thicknesses_training_M5',np.asarray(Y_val_[:,:n]).reshape(-1),fmt='%.7f')

np.savetxt('aRes_M1',np.asarray(aRes_M1).reshape(-1),fmt='%.7f')
np.savetxt('phas_M1',np.asarray(phas_M1).reshape(-1),fmt='%.7f')
np.savetxt('sig_sig_M1',np.asarray(sig[:,0:1,:]).reshape(-1),fmt='%.7f')
np.savetxt('sig_aRes_M1',np.asarray(sig_aRes_M1).reshape(-1),fmt='%.7f')
np.savetxt('sig_phas_M1',np.asarray(sig_phas_M1).reshape(-1),fmt='%.7f')

np.savetxt('aRes_M2',np.asarray(aRes_M2).reshape(-1),fmt='%.7f')
np.savetxt('phas_M2',np.asarray(phas_M2).reshape(-1),fmt='%.7f')
np.savetxt('sig_sig_M2',np.asarray(sig[:,1:2,:]).reshape(-1),fmt='%.7f')
np.savetxt('sig_aRes_M2',np.asarray(sig_aRes_M2).reshape(-1),fmt='%.7f')
np.savetxt('sig_phas_M2',np.asarray(sig_phas_M2).reshape(-1),fmt='%.7f')

np.savetxt('aRes_M3',np.asarray(aRes_M3).reshape(-1),fmt='%.7f')
np.savetxt('phas_M3',np.asarray(phas_M3).reshape(-1),fmt='%.7f')
np.savetxt('sig_sig_M3',np.asarray(sig[:,2:3,:]).reshape(-1),fmt='%.7f')
np.savetxt('sig_aRes_M3',np.asarray(sig_aRes_M3).reshape(-1),fmt='%.7f')
np.savetxt('sig_phas_M3',np.asarray(sig_phas_M3).reshape(-1),fmt='%.7f')

np.savetxt('aRes_M4',np.asarray(aRes_M4).reshape(-1),fmt='%.7f')
np.savetxt('phas_M4',np.asarray(phas_M4).reshape(-1),fmt='%.7f')
np.savetxt('sig_sig_M4',np.asarray(sig[:,3:4,:]).reshape(-1),fmt='%.7f')
np.savetxt('sig_aRes_M4',np.asarray(sig_aRes_M4).reshape(-1),fmt='%.7f')
np.savetxt('sig_phas_M4',np.asarray(sig_phas_M4).reshape(-1),fmt='%.7f')

np.savetxt('aRes_M5',np.asarray(aRes_M5).reshape(-1),fmt='%.7f')
np.savetxt('phas_M5',np.asarray(phas_M5).reshape(-1),fmt='%.7f')
np.savetxt('sig_sig_M5',np.asarray(sig[:,4:5,:]).reshape(-1),fmt='%.7f')
np.savetxt('sig_aRes_M5',np.asarray(sig_aRes_M5).reshape(-1),fmt='%.7f')
np.savetxt('sig_phas_M5',np.asarray(sig_phas_M5).reshape(-1),fmt='%.7f')

np.savetxt('aRes_MAP',np.asarray(aRes_MAP).reshape(-1),fmt='%.7f')
np.savetxt('phas_MAP',np.asarray(phas_MAP).reshape(-1),fmt='%.7f')
np.savetxt('sig_aRes_MAP',np.asarray(sig_aRes_MAP).reshape(-1),fmt='%.7f')
np.savetxt('sig_phas_MAP',np.asarray(sig_phas_MAP).reshape(-1),fmt='%.7f')

np.savetxt('prob',np.asarray(p).reshape(-1),fmt='%.7f')


