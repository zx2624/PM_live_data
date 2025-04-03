# 分析购买记录和最大损失
from pathlib import Path


def get_latest_log_directory(index=0):
    """获取最新的日志目录"""
    root_dir = Path(__file__).resolve().parent.parent
    log_root = root_dir / "logs"
    log_dirs = sorted(log_root.glob("202*"))
    if not log_dirs:
        raise FileNotFoundError("未找到日志目录")
    return log_dirs[index]


def analyze_purchases(log_dir):
    """分析购买记录

    Args:
        log_dir: 日志目录路径

    Returns:
        int: 购买总数
    """
    date = log_dir.name
    print(f"使用日志目录: {log_dir}")

    # 收集包含购买信息的日志行
    purchase_records = []
    for log_file in log_dir.glob("*.log"):
        if "main" in log_file.name:
            continue

        with open(log_file, "r") as f:
            lines = f.readlines()
            for line in lines:
                if "Im buying" in line:
                    purchase_records.append((str(log_file), line))
                    break

    # 打印购买记录
    purchase_count = 0
    for file_path, line in purchase_records:
        file_name = file_path.split(date)[1]
        # 去除路径分隔符和.log后缀
        file_name = file_name.strip("\\").strip("/").strip(".log")

        line = line.strip()
        purchase_info = " ".join(line.split("Im buying")[1:])
        print(f"{file_name}: {purchase_info}")
        purchase_count += 1

    print(f"总购买数: {purchase_count}")
    return purchase_count


def analyze_price_losses(log_dir):
    """分析价格损失

    Args:
        log_dir: 日志目录路径
    """
    logfiles = list(log_dir.glob("price*.log"))
    file_losses = {}
    keyword = ", ori_price:"

    # 收集每个文件的最大损失数据
    for log_file in logfiles:
        min_loss = 1.0
        latest_loss = 1.0
        min_line_number = -1

        with open(log_file, "r") as f:
            lines = f.readlines()
            for i, line in enumerate(lines):
                if keyword in line:
                    price_line = line.split(keyword)[1]
                    ori_price = float(price_line.split(",")[0])
                    cur_price = float(price_line.split(":")[1])
                    current_loss = cur_price - ori_price

                    if current_loss < min_loss:
                        min_loss = current_loss
                        min_line_number = i

                    latest_loss = current_loss

        file_losses[str(log_file)] = (min_loss, min_line_number, latest_loss)

    # 打印损失分析结果
    for file_path, (min_loss, line_number, latest_loss) in file_losses.items():
        print(
            (
                f"最小损失: {min_loss:.4f}, 最新损失: {latest_loss:.4f}, "
                f"{file_path}:{line_number+1}"
            )
        )


def main():
    """主函数"""
    try:
        log_dir = get_latest_log_directory()
        analyze_purchases(log_dir)
        analyze_price_losses(log_dir)
    except Exception as e:
        print(f"分析过程中出错: {e}")


if __name__ == "__main__":
    main()
