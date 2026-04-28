from .runner import ProcessosWorker


def main():
    ProcessosWorker.from_env().run_forever()


if __name__ == '__main__':
    main()
