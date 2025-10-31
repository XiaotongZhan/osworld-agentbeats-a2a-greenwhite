
# 1.Initialize

## 1.1 配置环境

```bash
# Conda 示例
conda env create -f environment.yml
conda activate cs294
poetry install --no-root
```

## 1.2 quickstart test

cd into third_party/osworld

set region
```bash
export AWS_REGION=us-east-1
```

then

```bash
python quickstart.py --provider_name aws --os_type Ubuntu
```