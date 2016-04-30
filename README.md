# growth-yield-batch

### An automated batch process to predict growth and yield for forest vegetation plots

Major goals include:

* Grow IDB plot data according to multiple silvicultural prescriptions using the Forest Vegetation Simulator (FVS).

* Automate the post-processing, parsing and organization of the FVS output; preps the input files for the harvest scheduler.

* Parrallelize the task load through an asyncronous task queue

* A dev environment using Vagrant/Puppet

<img src="https://raw.github.com/Ecotrust/growth-yield-batch/master/img/process_overview.png" alt="GYB Process Overview" />

## Initial deployment

#### Linux VM (recommended)
* Start virtual machine with `vagrant up`
* You'll need to install the FVS binaries into `/usr/local/bin`; currently this step is 
not automated and there are no Linux binaries available for distribution. Follow the
[build instructions](https://github.com/Ecotrust/growth-yield-batch/wiki/Building-FVS-binaries-on-Linux).
* You will have to restart services with `fab dev restart_services`
* To track status of celery tasks, visit the celery flower interface at `http://localhost:8082`

#### Linux VM (alternate)

Instructions assume a local Ubuntu machine.

* Install dependencies

        > sudo sh -c "echo 'deb http://download.virtualbox.org/virtualbox/debian '$(lsb_release -cs)' contrib non-free' > /etc/apt/sources.list.d/virtualbox.list"
        > wget -q http://download.virtualbox.org/virtualbox/debian/oracle_vbox.asc -O- | sudo apt-key add -
        > sudo apt-get update
        > sudo apt-get install virtualbox-5.0 vagrant git python-pip
        > sudo pip install 'ansible>=1.9.4'

* Clone repository, and checkout ansible branch

        > git clone git@github.com:jgcobb3/growth-yield-batch.git
        > cd growth-yield-batch
        > git fetch && git checkout ansible

* Save *Vagrantfile.template* as *Vagrantfile*

* Modify FVS variant selection in *growth-yield-batch/ansible/playbook.yml* by removing '#' comments.

* Provision virtual machine, FVS binaries will be built automatically.

        > vagrant up

* Track status of celery tasks at <http://localhost:5555>


#### Windows

* Install these python libraries: numpy, pandas and docopt
* Install FVS locally on a Windows machine; [download](http://www.fs.fed.us/fmsc/fvs/software/complete.shtml)... the contents will be in `C:/FVSBin`
* Note that many of the examples below use linux script name instead of the full .py filename. You'll need to call python and point to the full filename if running on windows. (e.g. Instead of `build_keys` you would use `C:\Python27\python.exe <FULLPATH>\build_keys.py`)

## Building the batch directory structure from base data

To build keyfiles in the proper directory structure from base data (.key, .fvs, .stdinfo), 
it's important that the input files conform to this file structure outlined below: 

### Project Directory structure
```
project_directory
|-- config.json
|-- cond
|   |-- 31566.cli
|   |-- 31566.fvs
|   |-- 31566.site
|   |-- 31566.rx
|   `-- 31566.std
`-- rx
    |-- varWC_rx1.key
    |-- varWC_rx25.key
    `-- include
        `-- spotted_owl.txt

```

##### config.json
JSON formatted file with variables that define the "multipliers"; e.g. variables
for which we calculate all permutations for each condition. Currently that is
just climate scenarios and offsets. (management prescriptions are the other multiplier
as defined in the `rx` directory)

Note: The `site_classes` object is *not* a multiplier; it is merely a lookup for 
the SITECODE keyword for variants where you want to override the default site
classes. For example, Western Cascades (WC) variant uses a 100 year based index.

```
{
  "climate_scenarios": [
    "Ensemble_rcp45",
    "Ensemble_rcp60",
    "Ensemble_rcp85",
    "NoClimate"
  ],
  "site_classes": {
    "WC": {
      "1": "SITECODE          DF       200         1",
      "2": "SITECODE          DF       170         1",
      "3": "SITECODE          DF       140         1",
      "4": "SITECODE          DF       110         1",
      "5": "SITECODE          DF        80         1"
    } 
  },
  "offsets": [
    0,
    5,
    10,
    15,
    20
  ]
}
```

##### cond/<condid>.cli

Climate file as per the [FVS climate extension](http://www.fs.fed.us/fmsc/fvs/whatis/climate-fvs.shtml)

##### cond/<condid>.fvs

FVS input tree lists, formatted according to the TREEFMT expected by your keyfiles.

##### cond/<condid>.std

Single line representing the FVS STDINFO keyword entry. Contains information about
plot location, slope, aspect, etc. See FVS manual for more details.

##### cond/<condid>.site

*Optionally* include a .site file to specify a single site class on which to run this 
particular condition. This must match one of the site classes specified for the variant 
in config.json *or* must be a number 1 through 5 corresponding to the default 
50 year Douglas Fir-based site classes:

**Default SITECODEs**
```
"1": "SITECODE          DF       148         1"
"2": "SITECODE          DF       125         1"
"3": "SITECODE          DF       105         1"
"4": "SITECODE          DF        85         1"
"5": "SITECODE          DF        62         1"
```
If .site file is not provided, site class "2" will be used by default.

##### cond/<condid>.rx

*Optionally* include a .rx file to specify which variants and prescriptions to run 
for each condition. The format is comma-delimited, no header, `variant,rxnum`:

```
PN,1
PN,22
PN,23
```
Or specify a wildcard to run every rx for a given variant.
```
PN,*
```
If a <condid>.rx file is not included, that condition will be run under every 
key file defined in the `rx` directory. 

##### rx/*.key files

These use the jinja2 templating language as placeholders for plot-specific variables.
For example, to refer to the condition id in the keyfile:
```
{{condid}}.fvs
```
The build process provides the following variables followed by an example:

```
 'climate': 'Ensemble_rcp45',
 'condid': '31566',
 'keyout': 'varWC_rx1_cond31566_site3_climEnsemble-rcp45_off0.key',
 'offset': 0,
 'out': 'varWC_rx1_cond31566_site3_climEnsemble-rcp45',
 'rx': '1',
 'site_class': '3',
 'sitecode': 'SiteCode          DF       105         1\n',
 'stdident': '31566    varWC_rx1_cond31566_site3_climEnsemble-rcp45',
 'stdinfo': 'STDINFO          617    CFS551        13                            61',
 'variant': 'WC',
```

##### rx/includes

You can also provide variant-level include files for common parts of you keyfile.
For example, if you wanted to have a common output database for all files. You could 
put this in your keyfile:

```
{{include.carbon_xls}}
```

And include a file named `rx/include/carbon_xls.txt` with the following contents:
```
DATABASE
DSNOut
FVSClimateOut.xls
CARBRPTS
END
```

Note the rx/include/**name**.txt corresponds exactly with the {{include.**name**}}
in the keyfile.


### Building Keys

Assuming you have set up your project directory according to the structure above:
```
$ cd project_directory
$ build_keys.py
Generating keyfiles for condition 31566
....
```

This will add a `plots` directory to the project with every combination of 
Rx, condition, site, climate model and offset:
```
|-- plots
|   |-- varWC_rx1_cond31566_site3_climEnsemble-rcp45
|   |   |-- 31566.cli
|   |   |-- 31566.fvs
|   |   |-- 31566.std
|   |   |-- varWC_rx1_cond31566_site3_climEnsemble-rcp45_off0.key
|   |   |-- varWC_rx1_cond31566_site3_climEnsemble-rcp45_off10.key
|   |   |-- varWC_rx1_cond31566_site3_climEnsemble-rcp45_off15.key
|   |   |-- varWC_rx1_cond31566_site3_climEnsemble-rcp45_off20.key
|   |   `-- varWC_rx1_cond31566_site3_climEnsemble-rcp45_off5.key
... etc ...
```

## Running FVS

There are three options for running FVS:

##### 1. Run the FVS exectuable directly. 
For newer versions that accept command line
parameters:
```
/usr/local/bin/FVSwcc --keywordfile=varWC_rx1_cond31566_site3_climEnsemble-rcp45_off0.key
```
Or on windows
```
C:\FVSBin\FVSwc.exe --keywordfile=varWC_rx1_cond31566_site3_climEnsemble-rcp45_off0.key
```
Note that this works in the current working directory and doesn't do any parsing or anything; useful for debugging keyfiles.

##### 2. Running a single plot, all offsets 


```
$ cd project_directory
$ build_keys.py
$ run_fvs.py plots/varWC_rx1_cond31566_site3_climEnsemble-rcp45/
$ run_fvs.py plots/varWC_rx1_cond31566_site3_climEnsemble-rcp60/
...
```


##### 3. Run all the project's plots in batch mode 

```
$ cd project_directory
$ build_keys.py
$ batch_fvs.py
```

`batch_fvs.py` also accepts a `--cores=<numcores>` parameter to provide *experimental* support 
for running batches on multiple cores in parallel. Testing indicates that adding cores will 
speed batch runs significantly, though the returns are not linear and diminish as you increase cores.
The optimal value will be equal to or slightly below the total number of cpu cores available on 
the system.


##### 4. Run all the project's plots in asynchronous batch mode

The prefered way to acheive parallel procesing is using the asych batch mode. 

This only works if you're running through the virtual machine or on a Linux-based server
instance. First you may need to confirm that celery is up and running

1. Check the number of nodes in `/etc/defaults/celeryd`
2. Restart celery `sudo service celeryd restart`
3. Check status `cd /var/celery && celery status`
4. Go...
```
$ cd project_directory
$ build_keys.py
$ batch_fvs_celery.py
```

## Outputs 
All working data is written to `work`. The FVS .out files are parsed and 
written to csvs in the `final` directory. There should be as many .csvs in `final`
as there are directories in `plots`. To check the status of a long running batch

```
$ cd project_directory
$ status_fvs
12 out of 160 done (including 2 failures)
```

## Combining csvs

```
cd /usr/local/data/out
# copy header
sed -n 1p `ls var*csv | head -n 1` > merged.csv
#copy all but the first line from all other files
for i in var*.csv; do sed 1d $i >> merged.csv ; done
```

For next steps on importing data to the Forest Planner
please review https://github.com/Ecotrust/land_owner_tools/wiki/Fixture-management#fvsaggregate-and-conditionvariantlookup

## Notes

* To check celery worker status (or execute other celery-related commands) on the remote machine `cd /var/celery && celery status`


### FVS Directory Structure and Naming requirements

Each run is named according to the following scheme:
```
var[VARIANT]_rx[RX]_cond[CONDID]_site[SITECLASS]_clim[CLIMATE SCENARIO]_off[OFFSET YEARS]
```

For example, using the Pacific Northwest variant, prescription 25, condition 43, and site class 2 with the Ensemble/rcp45 climate scenario and a 5 year offset:
```
varPN_rx25_cond43_site2_climEnsemble-rcp45_off5
```
