# Analysis of purchase records and maximum losses
from pathlib import Path


def get_latest_log_directory(index=0):
    """Get the latest log directory"""
    root_dir = Path(__file__).resolve().parent.parent
    log_root = root_dir / "logs"
    log_dirs = sorted(log_root.glob("202*"))
    if not log_dirs:
        raise FileNotFoundError("No log directory found")
    return log_dirs[index]


def analyze_purchases(log_dir):
    """Analyze purchase records

    Args:
        log_dir: Log directory path

    Returns:
        int: Total number of purchases
    """
    date = log_dir.name
    print(f"Using log directory: {log_dir}")

    # Collect log lines containing purchase information
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

    # Print purchase records
    purchase_count = 0
    for file_path, line in purchase_records:
        file_name = file_path.split(date)[1]
        # Remove path separators and .log suffix
        file_name = file_name.strip("\\").strip("/").strip(".log")

        line = line.strip()
        purchase_info = " ".join(line.split("Im buying")[1:])
        print(f"{file_name}: {purchase_info}")
        purchase_count += 1

    print(f"Total purchases: {purchase_count}")
    return purchase_count


def analyze_price_losses(log_dir):
    """Analyze price losses

    Args:
        log_dir: Log directory path
    """
    logfiles = list(log_dir.glob("price*.log"))
    file_losses = {}
    keyword = ", ori_price:"

    # Collect maximum loss data for each file
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
                    cur_price = float(price_line.split(":")[1].split(",")[0])
                    current_loss = cur_price - ori_price

                    if current_loss < min_loss:
                        min_loss = current_loss
                        min_line_number = i

                    latest_loss = current_loss

        file_losses[str(log_file)] = (min_loss, min_line_number, latest_loss)

    # Print loss analysis results
    for file_path, (min_loss, line_number, latest_loss) in file_losses.items():
        print(
            (
                f"Minimum loss: {min_loss}, Latest loss: {latest_loss}, "
                f"{file_path}:{line_number+1}"
            )
        )


def main():
    """Main function"""
    try:
        log_dir = get_latest_log_directory()
        analyze_purchases(log_dir)
        analyze_price_losses(log_dir)
    except Exception as e:
        print(f"Error during analysis: {e}")


if __name__ == "__main__":
    main()
