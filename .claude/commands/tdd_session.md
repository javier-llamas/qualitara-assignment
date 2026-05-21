# TDD Session

## Main objective

This is a TDD session. So our objective is to update tests and posibly identify issues in the implementation code.
You are not to make changes in implementation code before discussing and getting authorization for doing so.
You will run make test and look for code that is missing coverage and you will:

## CRITICAL: MUST USE YOUR practicing-tdd SKILL

## Implementation path

Review the use cases that these lines represent
Verify if MEANINGFUL tests can be done and weight the benefit of testing these use cases on the overall code base.
YOU WILL CREATE PLAN where that will include the objective of the tests, the component under test and the assertions
I will authorize this plan and then I will ask you to actually set up and create the test.
While creating the tests:

You will look into the confest.py file for any existing fixtures that can be useful
You will make sure that you cleanup every object you create and make sure fixtures or classes are not polluting other tests.
Check if you can parametrize so that we can keep tests clean
We use uv for running commands and pytest is our testing library.
Try to save tokens by running the tests you need and avoid verbosity if you don't need it. If you need to run the complete test suite make test gives you everything you need without being verbose.
AND REMEMBER testing is about increasing the quality of the software is covering not just filling a number.
