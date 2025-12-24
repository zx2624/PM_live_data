sudo apt-get intall git-lfs -y
git clone https://github.com/zx2624/py_clob.git  && cd pyclob && pip install -e .
cd ~
git clone https://github.com/zx2624/PM_live_data.git 
cd PM_live_data
git lfs pull
pip install -e .
pip install pandas
pip install httpx
pip intall web3==6.11.0
# env
